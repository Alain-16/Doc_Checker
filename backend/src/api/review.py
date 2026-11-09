import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from src.api.documents import DocumentOut, documents_by_id
from src.auth.dependencies import confirm_signature_or_401, current_user
from src.config.database import get_session
from src.models import Document, ReviewItem, User, VendorFile
from src.models.review import ReviewItemKind, ReviewResolution, ReviewStatus
from src.review.decisions import Correction, DecisionError, current_value, resolve

# Every signed-in role reviews (PRD: QA Analysts work the review queue). Each decision is signed.
router = APIRouter(prefix="/review-items", tags=["review queue"], dependencies=[Depends(current_user)])
MAX_PAGE_SIZE = 1000


class ReviewItemOut(BaseModel):
    id: uuid.UUID
    item_kind: ReviewItemKind
    status: ReviewStatus
    reason: str
    vendor_file_id: uuid.UUID
    filename: str
    page_number: int | None
    document_id: uuid.UUID | None
    document: DocumentOut | None
    # What the system decided, shown next to the source page.
    field: str
    value: str
    confidence: float | None
    detail: str | None
    correctable: bool
    correction_hint: str | None
    highlight: str | None  # text to mark on the source page
    # The decision, once made.
    resolution: ReviewResolution | None
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class Decision(BaseModel):
    resolution: ReviewResolution
    # For corrections: `value` for dates, attribute values and page text;
    # `document_type` (name) for a listed type, or `new_document_type` (a display name)
    # for one that isn't listed yet; `vendor_id` (+ `component_id`) for identification.
    value: str | None = None
    document_type: str | None = None
    new_document_type: str | None = Field(default=None, max_length=120)
    vendor_id: uuid.UUID | None = None
    component_id: uuid.UUID | None = None
    reason: str = Field(min_length=10, description="Why (audit trail).")
    password: str = Field(min_length=1, description="Your password, to sign the decision.")


class DecisionOut(BaseModel):
    item: ReviewItemOut
    documents_reevaluated: int


def covers(item_page, file_column):
    """A document of the same file whose page range holds the item's page."""
    return and_(Document.vendor_file_id == file_column, Document.start_page <= item_page, Document.end_page >= item_page)


def owning_document_ids(session: Session, items: list[ReviewItem]) -> dict[uuid.UUID, uuid.UUID]:
    """Item id -> its document. Page-level items (raised before the file was split,
    e.g. low-confidence OCR) have no document_id: they belong to the document whose
    page range covers their page."""
    out = {i.id: i.document_id for i in items if i.document_id}
    loose = [i for i in items if not i.document_id and i.page_number]
    if loose:
        rows = session.execute(
            select(Document.id, Document.vendor_file_id, Document.start_page, Document.end_page).where(
                Document.vendor_file_id.in_({i.vendor_file_id for i in loose})
            )
        ).all()
        for item in loose:
            for doc_id, file_id, start, end in rows:
                if file_id == item.vendor_file_id and start <= item.page_number <= end:
                    out[item.id] = doc_id
                    break
    return out


def items_out(session: Session, items: list[ReviewItem]) -> list[ReviewItemOut]:
    owners = owning_document_ids(session, items)
    documents = documents_by_id(session, list(set(owners.values())))
    files = {f.id: f.filename for f in session.scalars(select(VendorFile).where(VendorFile.id.in_({i.vendor_file_id for i in items})))}
    reviewers = {u.id: u.full_name for u in session.scalars(select(User).where(User.id.in_({i.resolved_by_id for i in items if i.resolved_by_id})))}
    out = []
    for item in items:
        current = current_value(session, item)
        out.append(
            ReviewItemOut(
                id=item.id,
                item_kind=item.item_kind,
                status=item.status,
                reason=item.reason,
                vendor_file_id=item.vendor_file_id,
                filename=files.get(item.vendor_file_id, ""),
                page_number=item.page_number,
                document_id=owners.get(item.id),
                document=documents.get(owners[item.id]) if item.id in owners else None,
                field=current.field,
                value=current.value,
                confidence=current.confidence,
                detail=current.detail,
                correctable=current.correctable,
                correction_hint=current.correction_hint,
                highlight=current.highlight,
                resolution=item.resolution,
                resolved_by=reviewers.get(item.resolved_by_id) if item.resolved_by_id else None,
                resolved_at=item.resolved_at,
                created_at=item.created_at,
            )
        )
    return out


@router.get("", response_model=list[ReviewItemOut])
def list_review_items(
    state: Literal["open", "resolved", "all"] = Query(default="open", alias="status"),
    document_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    vendor_file_id: uuid.UUID | None = None,
    limit: int = Query(default=200, gt=0, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_session),
) -> list[ReviewItemOut]:
    query = select(ReviewItem)
    if state != "all":
        query = query.where(ReviewItem.status == ReviewStatus(state))
    # Page-level items count as part of the document (and vendor) whose pages they are on.
    if document_id:
        document = session.get(Document, document_id)
        if document is None:
            return []
        query = query.where(
            or_(
                ReviewItem.document_id == document_id,
                and_(
                    ReviewItem.document_id.is_(None),
                    ReviewItem.vendor_file_id == document.vendor_file_id,
                    ReviewItem.page_number.between(document.start_page, document.end_page),
                ),
            )
        )
    if vendor_id:
        query = query.where(
            or_(
                exists().where(Document.id == ReviewItem.document_id, Document.vendor_id == vendor_id),
                and_(
                    ReviewItem.document_id.is_(None),
                    exists().where(covers(ReviewItem.page_number, ReviewItem.vendor_file_id), Document.vendor_id == vendor_id),
                ),
            )
        )
    if vendor_file_id:
        query = query.where(ReviewItem.vendor_file_id == vendor_file_id)
    # Oldest first: the queue is worked in the order things arrived.
    order = ReviewItem.created_at if state == "open" else ReviewItem.resolved_at.desc().nulls_last()
    items = list(session.scalars(query.order_by(order).limit(limit)))
    return items_out(session, items)


def get_item(session: Session, item_id: uuid.UUID) -> ReviewItem:
    item = session.get(ReviewItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review item not found.")
    return item


@router.get("/{item_id}", response_model=ReviewItemOut)
def read_review_item(item_id: uuid.UUID, session: Session = Depends(get_session)) -> ReviewItemOut:
    return items_out(session, [get_item(session, item_id)])[0]


@router.post("/{item_id}/resolve", response_model=DecisionOut)
def resolve_review_item(
    item_id: uuid.UUID,
    body: Decision,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> DecisionOut:
    """Confirm, correct or set aside one item. Signed; documents are re-judged at once."""
    item = get_item(session, item_id)
    if item.status != ReviewStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has already been decided.")
    confirm_signature_or_401(session, user, body.password)
    correction = Correction(
        value=body.value,
        document_type=body.document_type,
        new_document_type=body.new_document_type,
        vendor_id=body.vendor_id,
        component_id=body.component_id,
    )
    try:
        count = resolve(session, item, user, body.resolution, body.reason, correction)
    except DecisionError as error:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    session.commit()
    return DecisionOut(item=items_out(session, [item])[0], documents_reevaluated=count)
