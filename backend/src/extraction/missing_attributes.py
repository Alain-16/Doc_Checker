from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from src.models import CanonicalAttribute, ComplianceAttribute, Document, VendorFile
from src.models.compliance import AttributeStatus
from src.models.document import ResultMethod

# Need at least this many peers before drawing conclusions: "2 of 3 documents"
# is too thin to call something expected.
MIN_PEER_DOCUMENTS = 5
# An attribute is "expected" when at least 60% of peers state it. A starting
# guess, to tune once reviewers have judged real "not stated" findings.
EXPECTED_SHARE = 0.6


def peer_documents(document: Document):
    """Documents of the same type in other, current (not superseded) files.

    Returns a query, not rows: it's used inside the next two queries.
    """
    return (
        select(Document.id)
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .where(
            Document.document_type_id == document.document_type_id,
            VendorFile.superseded_by_id.is_(None),
            VendorFile.id != document.vendor_file_id,
        )
    )


def detect_for_document(session: Session, document: Document) -> None:
    peers = peer_documents(document)
    peer_count = session.scalar(select(func.count()).select_from(peers.subquery()))
    if peer_count < MIN_PEER_DOCUMENTS:
        return

    # How many peer documents state each canonical attribute.
    stated_counts = session.execute(
        select(ComplianceAttribute.canonical_attribute_id, func.count(distinct(ComplianceAttribute.document_id)))
        .where(
            ComplianceAttribute.document_id.in_(peers),
            ComplianceAttribute.status != AttributeStatus.NOT_STATED,
            ComplianceAttribute.canonical_attribute_id.is_not(None),
        )
        .group_by(ComplianceAttribute.canonical_attribute_id)
    ).all()

    already_stated = set(
        session.scalars(
            select(ComplianceAttribute.canonical_attribute_id).where(ComplianceAttribute.document_id == document.id)
        )
    )

    for canonical_id, count in stated_counts:
        share = count / peer_count
        if share < EXPECTED_SHARE or canonical_id in already_stated:
            continue
        canonical = session.get(CanonicalAttribute, canonical_id)
        # No page or snippet: there's nothing on the page to cite. The table's
        # CHECK allows that only for "not_stated".
        session.add(
            ComplianceAttribute(
                document_id=document.id,
                canonical_attribute_id=canonical_id,
                name_as_written=canonical.display_name,
                statement=None,
                status=AttributeStatus.NOT_STATED,
                page_number=None,
                evidence_snippet=None,
                extraction_method=ResultMethod.RULES,
                # How strongly peers suggest it should be stated.
                confidence=round(share, 4),
                mapping_confidence=1.0,
            )
        )


def detect_not_stated(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage (Feature 6, step 3)."""
    documents = session.scalars(
        select(Document).where(
            Document.vendor_file_id == vendor_file.id,
            Document.document_type_id.is_not(None),
        )
    ).all()
    for document in documents:
        if document.document_type and document.document_type.name != "unknown":
            detect_for_document(session, document)