"""Review queue decisions (Feature 8): a person confirms, corrects, or sets aside an uncertain result.

Every decision is electronically signed (meaning "review") and recorded in the
audit trail with its reason. A correction is written to the record the item is
about; the old value stays in the audit trail. Afterwards the documents of the
file's vendors are re-judged, so statuses and findings follow the decision at once.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from src.audit.trail import set_audit_reason
from src.auth.signatures import sign
from src.compliance.attributes import add_document_type
from src.compliance.evaluation import evaluate_compliance
from src.models import (
    Component,
    Document,
    DocumentAttribute,
    DocumentDate,
    DocumentType,
    Page,
    ReviewItem,
    User,
    Vendor,
    VendorFile,
)
from src.models.audit import SignatureMeaning
from src.models.compliance import AttributeValueType, StatusValue
from src.models.document import DatePrecision, DocumentTypeOrigin, ResultMethod
from src.models.review import ReviewItemKind, ReviewResolution, ReviewStatus

HUMAN_CONFIDENCE = 1.0
EXCERPT_CHARS = 600


class DecisionError(Exception):
    """The decision can't be applied as given (wrong state, unsupported correction, bad value)."""


@dataclass
class CurrentValue:
    """What the system decided, shown to the reviewer next to the source page."""

    field: str  # "Issue date", "Document type", "Page 3 text", ...
    value: str  # as the reviewer reads it
    confidence: float | None
    detail: str | None  # e.g. the original text the date was read from
    correctable: bool  # can this kind be corrected here (vs. only confirmed or set aside)
    correction_hint: str | None  # what to type when correcting
    highlight: str | None = None  # text to mark on the source page


def current_value(session: Session, item: ReviewItem) -> CurrentValue:
    kind = item.item_kind
    if kind == ReviewItemKind.DATE:
        d = session.get(DocumentDate, item.target_record_id)
        if d is None:
            return CurrentValue("Date", "Record no longer exists", None, None, False, None)
        return CurrentValue(
            f"{d.date_type.value.capitalize()} date",
            d.date_value.isoformat() if d.precision == DatePrecision.DAY else f"{d.date_value.isoformat()} ({d.precision.value} precision)",
            d.confidence,
            f"Read as “{d.original_text}”" + (" — ambiguous" if d.is_ambiguous else ""),
            True,
            "The date as YYYY-MM-DD",
            d.original_text,
        )
    if kind == ReviewItemKind.ATTRIBUTE_VALUE:
        a = session.get(DocumentAttribute, item.target_record_id)
        if a is None:
            return CurrentValue("Attribute", "Record no longer exists", None, None, False, None)
        attribute = a.key_attribute
        shown = "Not stated" if a.value is None else a.value if isinstance(a.value, str) else json.dumps(a.value)
        return CurrentValue(
            attribute.display_name, shown, a.confidence, a.evidence_snippet, True, value_hint(attribute.value_type), a.evidence_snippet
        )
    if kind == ReviewItemKind.DOCUMENT_TYPE:
        doc = session.get(Document, item.target_record_id)
        if doc is None:
            return CurrentValue("Document type", "Record no longer exists", None, None, False, None)
        label = doc.document_type.display_name if doc.document_type else "Unclassified"
        return CurrentValue("Document type", label, doc.classification_confidence, doc.title, True, "Choose the document type")
    if kind == ReviewItemKind.VENDOR_IDENTIFICATION:
        doc = session.get(Document, item.target_record_id)
        if doc is None:
            return CurrentValue("Vendor and component", "Record no longer exists", None, None, False, None)
        names = " / ".join(n for n in (doc.vendor.name if doc.vendor else None, doc.component.name if doc.component else None) if n)
        return CurrentValue("Vendor and component", names or "Not identified", None, None, True, "Choose the vendor and component")
    if kind == ReviewItemKind.PAGE_TEXT:
        page = session.get(Page, item.target_record_id)
        if page is None:
            return CurrentValue("Page text", "Record no longer exists", None, None, False, None)
        return CurrentValue(f"Page {page.page_number} text", page.text[:EXCERPT_CHARS], page.confidence, page.extraction_engine, True, "The page text as it reads")
    if kind == ReviewItemKind.SEGMENT_BOUNDARY:
        doc = session.get(Document, item.target_record_id)
        shown = f"Pages {doc.start_page}–{doc.end_page}" if doc else "Record no longer exists"
        return CurrentValue("Document boundary", shown, doc.segmentation_confidence if doc else None, None, False, None)
    return CurrentValue(kind.value.replace("_", " ").capitalize(), "", None, None, False, None)


def value_hint(value_type: AttributeValueType) -> str:
    return {
        AttributeValueType.TEXT: "The value as written",
        AttributeValueType.TEXT_LIST: "Values separated by commas",
        AttributeValueType.DATE: "The date as YYYY-MM-DD",
        AttributeValueType.STATUS: "yes, no or conditional",
        AttributeValueType.NUMBER: "A number",
        AttributeValueType.RECORDS: 'JSON rows, e.g. [{"lot_number": "…"}]',
    }[value_type]


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as error:
        raise DecisionError("Write the date as YYYY-MM-DD.") from error


def parse_attribute(value_type: AttributeValueType, text: str, record_fields: list[str]) -> Any:
    text = text.strip()
    if value_type == AttributeValueType.TEXT:
        return text
    if value_type == AttributeValueType.TEXT_LIST:
        return [part.strip() for part in text.split(",") if part.strip()]
    if value_type == AttributeValueType.DATE:
        return parse_date(text).isoformat()
    if value_type == AttributeValueType.STATUS:
        if text.lower() not in {s.value for s in StatusValue}:
            raise DecisionError("Answer yes, no or conditional.")
        return text.lower()
    if value_type == AttributeValueType.NUMBER:
        try:
            return float(text)
        except ValueError as error:
            raise DecisionError("Write a number.") from error
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as error:
        raise DecisionError("Write the rows as JSON.") from error
    if not isinstance(rows, list) or not all(isinstance(r, dict) and set(r) <= set(record_fields) for r in rows):
        raise DecisionError(f"Each row must be an object with only these fields: {', '.join(record_fields)}.")
    return rows


@dataclass
class Correction:
    value: str | None = None
    document_type: str | None = None  # name of an existing type
    new_document_type: str | None = None  # display name typed by the reviewer, when the type isn't listed
    vendor_id: uuid.UUID | None = None
    component_id: uuid.UUID | None = None


def apply_correction(session: Session, item: ReviewItem, correction: Correction) -> None:
    """Write the reviewer's value into the record. The audit trail keeps the old one."""
    kind = item.item_kind
    if kind == ReviewItemKind.DATE:
        record = session.get(DocumentDate, item.target_record_id)
        if record is None or not correction.value:
            raise DecisionError("Give the correct date.")
        record.date_value = parse_date(correction.value)
        record.precision = DatePrecision.DAY
        record.is_ambiguous = False
        record.extraction_method = ResultMethod.HUMAN
        record.confidence = HUMAN_CONFIDENCE
    elif kind == ReviewItemKind.ATTRIBUTE_VALUE:
        record = session.get(DocumentAttribute, item.target_record_id)
        if record is None or correction.value is None:
            raise DecisionError("Give the correct value.")
        attribute = record.key_attribute
        record.value = parse_attribute(attribute.value_type, correction.value, attribute.record_fields)
        # A stated value must point at its evidence: keep the page the reviewer looked at.
        record.page_number = record.page_number or item.page_number
        record.evidence_snippet = record.evidence_snippet or f"Corrected by a reviewer: {correction.value.strip()}"
        record.extraction_method = ResultMethod.HUMAN
        record.confidence = HUMAN_CONFIDENCE
    elif kind == ReviewItemKind.DOCUMENT_TYPE:
        document = session.get(Document, item.target_record_id)
        if document is None:
            raise DecisionError("The document no longer exists.")
        if correction.new_document_type and correction.new_document_type.strip():
            document_type = name_document_type(session, correction.new_document_type.strip(), document)
        else:
            document_type = session.scalar(select(DocumentType).where(DocumentType.name == correction.document_type))
        if document_type is None:
            raise DecisionError("Choose a document type, or type the name of a new one.")
        document.document_type_id = document_type.id
        document.classification_method = ResultMethod.HUMAN
        document.classification_confidence = HUMAN_CONFIDENCE
    elif kind == ReviewItemKind.VENDOR_IDENTIFICATION:
        document = session.get(Document, item.target_record_id)
        vendor = session.get(Vendor, correction.vendor_id) if correction.vendor_id else None
        component = session.get(Component, correction.component_id) if correction.component_id else None
        if document is None or vendor is None:
            raise DecisionError("Choose the vendor.")
        if component is not None and component.vendor_id != vendor.id:
            raise DecisionError("That component belongs to another vendor.")
        document.vendor_id = vendor.id
        document.component_id = component.id if component else None
    elif kind == ReviewItemKind.PAGE_TEXT:
        page = session.get(Page, item.target_record_id)
        if page is None or not correction.value or not correction.value.strip():
            raise DecisionError("Give the page text.")
        page.text = correction.value
        page.confidence = HUMAN_CONFIDENCE
    else:
        raise DecisionError("This kind of item can only be confirmed or marked not applicable here.")


MIN_TYPE_NAME_CHARS = 3


def name_document_type(session: Session, display_name: str, document: Document) -> DocumentType:
    """The type a reviewer typed. A practically identical existing type is reused
    (and brought back if retired), so "Certificate of analysis" doesn't duplicate
    "Certificate of Analysis". A genuinely new type is "discovered": a real document
    showed it, a person named it. The classifier offers it for later documents."""
    if len(display_name) < MIN_TYPE_NAME_CHARS:
        raise DecisionError("Type a document type name of at least 3 characters.")
    existing = set(session.scalars(select(DocumentType.id)))
    document_type = add_document_type(
        session,
        display_name,
        f"Named by a reviewer for a document of pages {document.start_page}-{document.end_page}"
        + (f" titled “{document.title}”." if document.title else "."),
    )
    if document_type.id not in existing:
        document_type.origin = DocumentTypeOrigin.DISCOVERED
    return document_type


def resolve(
    session: Session,
    item: ReviewItem,
    reviewer: User,
    resolution: ReviewResolution,
    reason: str,
    correction: Correction | None,
) -> int:
    """Record and sign the decision, apply any correction, then re-judge. Returns documents re-judged.

    The caller has already checked the reviewer's password and commits afterwards.
    """
    if item.status != ReviewStatus.OPEN:
        raise DecisionError("This item has already been decided.")
    set_audit_reason(session, reason)
    if resolution == ReviewResolution.CORRECTED:
        apply_correction(session, item, correction or Correction())

    decided = {
        "status": ReviewStatus.RESOLVED,
        "resolution": resolution,
        "resolved_by_id": reviewer.id,
        "resolved_at": datetime.now(UTC),
    }
    # sign() flushes the session, and the table only accepts a resolved row that
    # already carries its signature. So the signature is taken on a detached copy
    # holding the final values (same content, same fingerprint), then the real
    # row gets the values and the signature together in one UPDATE.
    columns = {a.key: getattr(item, a.key) for a in inspect(item).mapper.column_attrs}
    signed_copy = ReviewItem(**{**columns, **decided})
    signature = sign(session, reviewer, SignatureMeaning.REVIEW, signed_copy, reason)
    for key, value in decided.items():
        setattr(item, key, value)
    item.signature_id = signature.id
    session.flush()

    vendor_file = session.get(VendorFile, item.vendor_file_id)
    if vendor_file is None:
        return 0
    evaluate_compliance(session, vendor_file)
    return len(vendor_file.documents)
