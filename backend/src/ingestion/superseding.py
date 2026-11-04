from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

import uuid

from src.classification.classifier import UNKNOWN_TYPE
from src.models import Component, Document, DocumentAttribute, KeyAttribute, Vendor, VendorFile
from src.vendors.identification import product_key

# The core key attribute listing the items a document covers.
ITEMS_ATTRIBUTE = "item_numbers"


def same_document_line(document: Document):
    """Conditions for "an earlier or later version of this document".

    Same component (or, for a company-level document, same vendor and no
    component) and same type, from ANOTHER upload (documents of one bundle
    never replace each other). When both have a document number it must match:
    two Certificates of Analysis for different lots are both valid, not
    versions of one another.
    """
    if document.component_id is not None:
        subject = [Document.component_id == document.component_id]
    else:
        subject = [Document.vendor_id == document.vendor_id, Document.component_id.is_(None)]
    conditions = [
        *subject,
        Document.document_type_id == document.document_type_id,
        Document.vendor_file_id != document.vendor_file_id,
        Document.superseded_by_id.is_(None),
    ]
    if document.document_number:
        conditions.append(
            or_(Document.document_number.is_(None), Document.document_number == document.document_number)
        )
    return conditions


def covered_items(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    """Each document's item numbers, normalized ("4432/50 Grey" -> "443250grey"). Missing = empty."""
    rows = session.execute(
        select(DocumentAttribute.document_id, DocumentAttribute.value)
        .join(KeyAttribute, DocumentAttribute.key_attribute_id == KeyAttribute.id)
        .where(KeyAttribute.name == ITEMS_ATTRIBUTE, DocumentAttribute.document_id.in_(document_ids))
    ).all()
    items: dict[uuid.UUID, set[str]] = {}
    for document_id, value in rows:
        values = value if isinstance(value, list) else [value] if value else []
        items[document_id] = {product_key(str(v)) for v in values if v}
    return items


def about_same_items(mine: set[str], theirs: set[str]) -> bool:
    """Two same-type documents covering different items (a bulletin for the
    stopper, another for its coating) are not versions of one another.
    Unknown on either side: can't tell them apart, so they may be."""
    return not mine or not theirs or bool(mine & theirs)


def supersede_document(session: Session, document: Document) -> None:
    """Keep exactly one current version of each document line.

    "Newer" means its file was uploaded later (created_at), not "finished
    processing later": a small file uploaded second can finish before a big
    file uploaded first, and its document must still be the current one.

    Old rows are never deleted or changed beyond the two superseded_* columns,
    so the audit history stays complete (Feature 1, step 4). Also called by the
    review queue, once a person identifies an uncertain document's component.
    """
    if document.vendor_id is None or document.document_type_id is None:
        return  # waiting for review; nothing can be superseded yet
    if document.document_type.name == UNKNOWN_TYPE:
        return  # two unclassified documents are not versions of each other

    # Lock the subject's row: two uploads for the same component (or vendor)
    # finishing at the same moment take turns here instead of each superseding the other.
    if document.component_id is not None:
        session.get(Component, document.component_id, with_for_update=True)
    else:
        session.get(Vendor, document.vendor_id, with_for_update=True)
    uploaded_at = session.scalar(select(VendorFile.created_at).where(VendorFile.id == document.vendor_file_id))

    others = session.execute(
        select(Document, VendorFile.created_at)
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .where(*same_document_line(document))
        .order_by(VendorFile.created_at.desc())
    ).all()
    items = covered_items(session, [document.id, *(other.id for other, _ in others)])
    mine = items.get(document.id, set())
    others = [(other, created_at) for other, created_at in others if about_same_items(mine, items.get(other.id, set()))]

    # --- Is a newer version already on file? Then THIS one is old ---
    newer = [other for other, created_at in others if created_at > uploaded_at]
    if newer:
        document.superseded_by_id = newer[0].id
        document.superseded_at = func.now()
        return

    # --- Otherwise this is the newest: supersede the older current ones ---
    for other, created_at in others:
        if created_at < uploaded_at:
            other.superseded_by_id = document.id
            other.superseded_at = func.now()


def supersede_older_documents(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: supersede per document, for every document of the file."""
    documents = session.scalars(
        select(Document)
        .where(Document.vendor_file_id == vendor_file.id)
        .order_by(Document.start_page)
    ).all()
    for document in documents:
        supersede_document(session, document)
    session.flush()
