import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.auth.dependencies import current_user
from src.config.database import get_session
from src.models import (
    ComplianceFinding,
    ComplianceRule,
    ComplianceRuleVersion,
    Component,
    Document,
    DocumentAttribute,
    DocumentDate,
    DocumentType,
    Page,
    ReviewItem,
    Vendor,
    VendorFile,
)
from src.models.document import ComplianceStatus
from src.models.review import ReviewStatus
from src.models.vendor_file import ProcessingStatus

# Read-only views of what the pipeline produced (Features 3-7). Every signed-in role reads them.
router = APIRouter(tags=["documents"], dependencies=[Depends(current_user)])
MAX_PAGE_SIZE = 2000


# --- Shapes ---


class DocumentOut(BaseModel):
    """One logical document: what it is, whose, where it sits in its file, and its status."""

    id: uuid.UUID
    label: str  # "Compliance Bulletin CB-4432 Rev 11", or "Unclassified, pages 18-23"
    title: str | None
    document_type: str | None  # name, e.g. "compliance_bulletin"
    document_type_label: str | None
    document_number: str | None
    revision: str | None
    vendor_id: uuid.UUID | None
    vendor_name: str | None
    component_id: uuid.UUID | None
    component_name: str | None
    vendor_file_id: uuid.UUID
    filename: str
    start_page: int
    end_page: int
    governing_date: date | None
    compliance_status: ComplianceStatus
    status_reason: str | None
    status_evaluated_at: datetime | None
    superseded: bool
    superseded_by_id: uuid.UUID | None
    classification_confidence: float | None
    segmentation_confidence: float
    open_findings: int
    open_reviews: int
    created_at: datetime


class DateOut(BaseModel):
    id: uuid.UUID
    date_type: str
    date_value: date
    precision: str
    original_text: str
    is_document_date: bool
    is_ambiguous: bool
    page_number: int
    evidence_snippet: str
    extraction_method: str
    confidence: float


class AttributeValueOut(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    value_type: str
    value: Any  # None = not stated
    page_number: int | None
    evidence_snippet: str | None
    extraction_method: str
    confidence: float


class FindingBrief(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_code: str
    rule_name: str
    rule_version: int
    status: ComplianceStatus
    severity: str
    message: str
    evidence: dict[str, Any]
    governing_date: date | None
    created_at: datetime
    resolved: bool
    resolved_at: datetime | None


class ReviewBrief(BaseModel):
    id: uuid.UUID
    item_kind: str
    reason: str
    page_number: int | None


class DocumentDetailOut(DocumentOut):
    identification_evidence: dict[str, Any]
    segmentation_evidence: dict[str, Any]
    extracted_fields: dict[str, Any]
    classification_method: str | None
    dates: list[DateOut]
    attributes: list[AttributeValueOut]
    findings: list[FindingBrief]  # open first, then history
    reviews: list[ReviewBrief]  # open review items about this document
    supersedes: list[DocumentOut]  # older versions this one replaced
    superseded_by: DocumentOut | None


class PageOut(BaseModel):
    page_number: int
    text: str
    source_type: str
    extraction_engine: str
    confidence: float


class VendorFileOut(BaseModel):
    id: uuid.UUID
    filename: str
    page_count: int
    file_size_bytes: int
    status: ProcessingStatus
    error: str | None
    created_at: datetime
    document_count: int
    vendor_names: list[str]


class DocumentTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: str
    origin: str
    active: bool
    document_count: int  # current (not superseded) documents
    active_rules: int


# --- Building the shapes (also used by findings and review) ---


def document_label(document: Document, type_label: str | None) -> str:
    if not type_label:
        return f"Unclassified, pages {document.start_page}-{document.end_page}"
    parts = [type_label]
    if document.document_number:
        parts.append(document.document_number)
    if document.revision:
        parts.append(f"Rev {document.revision}")
    return " ".join(parts)


def documents_query() -> Select:
    """Documents with what every list shows; counts of open findings and reviews as subqueries."""
    open_findings = (
        select(func.count())
        .where(ComplianceFinding.document_id == Document.id, ComplianceFinding.resolved.is_(False))
        .correlate(Document)
        .scalar_subquery()
    )
    open_reviews = (
        select(func.count())
        .where(ReviewItem.document_id == Document.id, ReviewItem.status == ReviewStatus.OPEN)
        .correlate(Document)
        .scalar_subquery()
    )
    return (
        select(Document, DocumentType, Vendor.name, Component.name, VendorFile.filename, open_findings, open_reviews)
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .outerjoin(DocumentType, Document.document_type_id == DocumentType.id)
        .outerjoin(Vendor, Document.vendor_id == Vendor.id)
        .outerjoin(Component, Document.component_id == Component.id)
    )


def document_out(row: Any) -> DocumentOut:
    document, document_type, vendor_name, component_name, filename, findings, reviews = row
    type_label = document_type.display_name if document_type else None
    return DocumentOut(
        id=document.id,
        label=document_label(document, type_label),
        title=document.title,
        document_type=document_type.name if document_type else None,
        document_type_label=type_label,
        document_number=document.document_number,
        revision=document.revision,
        vendor_id=document.vendor_id,
        vendor_name=vendor_name,
        component_id=document.component_id,
        component_name=component_name,
        vendor_file_id=document.vendor_file_id,
        filename=filename,
        start_page=document.start_page,
        end_page=document.end_page,
        governing_date=document.governing_date,
        compliance_status=document.compliance_status,
        status_reason=document.status_reason,
        status_evaluated_at=document.status_evaluated_at,
        superseded=document.superseded_by_id is not None,
        superseded_by_id=document.superseded_by_id,
        classification_confidence=document.classification_confidence,
        segmentation_confidence=document.segmentation_confidence,
        open_findings=findings or 0,
        open_reviews=reviews or 0,
        created_at=document.created_at,
    )


def documents_by_id(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, DocumentOut]:
    if not ids:
        return {}
    rows = session.execute(documents_query().where(Document.id.in_(ids))).all()
    return {row[0].id: document_out(row) for row in rows}


def finding_brief(finding: ComplianceFinding, version: ComplianceRuleVersion) -> FindingBrief:
    return FindingBrief(
        id=finding.id,
        rule_id=version.rule_id,
        rule_code=finding.rule_code,
        rule_name=version.name,
        rule_version=version.version,
        status=finding.status,
        severity=finding.severity,
        message=finding.message,
        evidence=finding.evidence,
        governing_date=finding.governing_date,
        created_at=finding.created_at,
        resolved=finding.resolved,
        resolved_at=finding.resolved_at,
    )


# --- Documents ---


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    vendor_id: uuid.UUID | None = None,
    component_id: uuid.UUID | None = None,
    vendor_file_id: uuid.UUID | None = None,
    document_type: str | None = Query(default=None, description="Document type name."),
    compliance_status: ComplianceStatus | None = Query(default=None, alias="status"),
    include_superseded: bool = True,
    q: str | None = Query(default=None, description="Matches title, number, type, vendor, component, file name."),
    limit: int = Query(default=500, gt=0, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_session),
) -> list[DocumentOut]:
    query = documents_query()
    if vendor_id:
        query = query.where(Document.vendor_id == vendor_id)
    if component_id:
        query = query.where(Document.component_id == component_id)
    if vendor_file_id:
        query = query.where(Document.vendor_file_id == vendor_file_id)
    if document_type:
        query = query.where(DocumentType.name == document_type)
    if compliance_status:
        query = query.where(Document.compliance_status == compliance_status, Document.superseded_by_id.is_(None))
    if not include_superseded:
        query = query.where(Document.superseded_by_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            or_(
                Document.title.ilike(like),
                Document.document_number.ilike(like),
                DocumentType.display_name.ilike(like),
                Vendor.name.ilike(like),
                Component.name.ilike(like),
                VendorFile.filename.ilike(like),
            )
        )
    # Newest files first; within a file, in page order (how the bundle reads).
    query = query.order_by(VendorFile.created_at.desc(), Document.start_page).limit(limit)
    return [document_out(row) for row in session.execute(query).all()]


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def read_document(document_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentDetailOut:
    row = session.execute(documents_query().where(Document.id == document_id)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    document: Document = row[0]
    base = document_out(row)

    dates = session.scalars(
        select(DocumentDate).where(DocumentDate.document_id == document.id).order_by(DocumentDate.page_number)
    ).all()
    attributes = session.scalars(
        select(DocumentAttribute)
        .where(DocumentAttribute.document_id == document.id)
        .options(selectinload(DocumentAttribute.key_attribute))
    ).all()
    findings = session.execute(
        select(ComplianceFinding, ComplianceRuleVersion)
        .join(ComplianceRuleVersion, ComplianceFinding.rule_version_id == ComplianceRuleVersion.id)
        .where(ComplianceFinding.document_id == document.id)
        .order_by(ComplianceFinding.resolved, ComplianceFinding.created_at.desc())
    ).all()
    reviews = session.scalars(
        select(ReviewItem)
        .where(ReviewItem.document_id == document.id, ReviewItem.status == ReviewStatus.OPEN)
        .order_by(ReviewItem.created_at)
    ).all()
    older_ids = list(session.scalars(select(Document.id).where(Document.superseded_by_id == document.id)))
    related = documents_by_id(session, [*older_ids, *([document.superseded_by_id] if document.superseded_by_id else [])])

    return DocumentDetailOut(
        **base.model_dump(),
        identification_evidence=document.identification_evidence,
        segmentation_evidence=document.segmentation_evidence,
        extracted_fields=document.extracted_fields,
        classification_method=document.classification_method,
        dates=[DateOut.model_validate(d, from_attributes=True) for d in dates],
        attributes=sorted(
            (
                AttributeValueOut(
                    id=a.id,
                    name=a.key_attribute.name,
                    display_name=a.key_attribute.display_name,
                    value_type=a.key_attribute.value_type,
                    value=a.value,
                    page_number=a.page_number,
                    evidence_snippet=a.evidence_snippet,
                    extraction_method=a.extraction_method,
                    confidence=a.confidence,
                )
                for a in attributes
            ),
            key=lambda a: (a.page_number or 10**6, a.display_name),
        ),
        findings=[finding_brief(f, v) for f, v in findings],
        reviews=[ReviewBrief(id=r.id, item_kind=r.item_kind, reason=r.reason, page_number=r.page_number) for r in reviews],
        supersedes=[related[i] for i in older_ids if i in related],
        superseded_by=related.get(document.superseded_by_id) if document.superseded_by_id else None,
    )


# --- Vendor files: the list, and their pages as read ---


@router.get("/vendor-files", response_model=list[VendorFileOut])
def list_vendor_files(
    vendor_id: uuid.UUID | None = None,
    limit: int = Query(default=100, gt=0, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_session),
) -> list[VendorFileOut]:
    query = select(VendorFile).options(selectinload(VendorFile.documents).selectinload(Document.vendor))
    if vendor_id:
        query = query.where(VendorFile.documents.any(Document.vendor_id == vendor_id))
    files = session.scalars(query.order_by(VendorFile.created_at.desc()).limit(limit)).all()
    return [
        VendorFileOut(
            id=f.id,
            filename=f.filename,
            page_count=f.page_count,
            file_size_bytes=f.file_size_bytes,
            status=f.processing_status,
            error=f.processing_state.get("error"),
            created_at=f.created_at,
            document_count=len(f.documents),
            vendor_names=sorted({d.vendor.name for d in f.documents if d.vendor}),
        )
        for f in files
    ]


@router.get("/vendor-files/{vendor_file_id}/pages", response_model=list[PageOut])
def read_pages(
    vendor_file_id: uuid.UUID,
    first: int = Query(default=1, ge=1, alias="from"),
    last: int | None = Query(default=None, ge=1, alias="to"),
    session: Session = Depends(get_session),
) -> list[Page]:
    """The text of each page as read (digital text layer or OCR), for the side-by-side viewer."""
    if session.get(VendorFile, vendor_file_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor file not found")
    query = select(Page).where(Page.vendor_file_id == vendor_file_id, Page.page_number >= first)
    if last is not None:
        query = query.where(Page.page_number <= last)
    return list(session.scalars(query.order_by(Page.page_number)))


# --- Document types ---


@router.get("/document-types", response_model=list[DocumentTypeOut])
def list_document_types(session: Session = Depends(get_session)) -> list[DocumentTypeOut]:
    counts = dict(
        session.execute(
            select(Document.document_type_id, func.count())
            .join(VendorFile, Document.vendor_file_id == VendorFile.id)
            .where(Document.superseded_by_id.is_(None), VendorFile.processing_status == ProcessingStatus.COMPLETED)
            .group_by(Document.document_type_id)
        ).all()
    )
    rules = session.scalars(select(ComplianceRule).options(selectinload(ComplianceRule.versions))).all()
    active_by_type: dict[uuid.UUID, int] = {}
    for rule in rules:
        if rule.document_type_id and rule.versions and rule.current.active:
            active_by_type[rule.document_type_id] = active_by_type.get(rule.document_type_id, 0) + 1
    types = session.scalars(select(DocumentType).order_by(DocumentType.display_name)).all()
    return [
        DocumentTypeOut(
            id=t.id,
            name=t.name,
            display_name=t.display_name,
            description=t.description,
            origin=t.origin,
            active=t.active,
            document_count=counts.get(t.id, 0),
            active_rules=active_by_type.get(t.id, 0),
        )
        for t in types
    ]
