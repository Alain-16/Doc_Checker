import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Component, Document, DocumentType, Vendor, VendorFile
from src.models.document import ComplianceStatus


@dataclass
class DocumentContext:
    """What a reader needs to judge a source: which document, and can it be trusted today?"""

    document_id: uuid.UUID
    label: str  # "Compliance Bulletin, pages 6-12 (West Pharmaceutical Services, Inc. / 4432/50 Gray FC)"
    status: ComplianceStatus
    status_reason: str | None
    governing_date: date | None
    superseded: bool


@dataclass
class Source:
    """One numbered piece of evidence: a passage, a database record, or a finding."""

    kind: str  # "passage" | "record" | "finding" | "summary" (a count from the database)
    text: str  # what the answer may use
    context: DocumentContext | None  # None for component-level findings
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    number: int = 0  # set when the sources are numbered for the answer

    def as_json(self) -> dict[str, Any]:
        """What the API returns and the message stores: everything the citation shows."""
        context = self.context
        return {
            "number": self.number,
            "kind": self.kind,
            "document_id": str(context.document_id) if context else None,
            "document": context.label if context else None,
            "pages": [self.page_start, self.page_end] if self.page_start else None,
            "section": self.section,
            "compliance_status": context.status.value if context else None,
            "status_reason": context.status_reason if context else None,
            "superseded": context.superseded if context else False,
            "excerpt": self.text[:400],
        }


def document_contexts(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, DocumentContext]:
    """Label and status of each document, read fresh (never copied onto chunks: they'd go stale)."""
    rows = session.execute(
        select(Document, DocumentType.display_name, VendorFile.superseded_by_id, Vendor.name, Component.name)
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .outerjoin(DocumentType, Document.document_type_id == DocumentType.id)
        .outerjoin(Component, VendorFile.component_id == Component.id)
        .outerjoin(Vendor, Component.vendor_id == Vendor.id)
        .where(Document.id.in_(document_ids))
    ).all()
    contexts = {}
    for document, type_name, superseded_by, vendor, component in rows:
        owner = " / ".join(name for name in (vendor, component) if name)
        contexts[document.id] = DocumentContext(
            document_id=document.id,
            label=f"{type_name or 'Unclassified document'}, pages {document.start_page}-{document.end_page}"
            + (f" ({owner})" if owner else ""),
            status=document.compliance_status,
            status_reason=document.status_reason,
            governing_date=document.governing_date,
            superseded=superseded_by is not None,
        )
    return contexts


def number_sources(sources: list[Source]) -> list[Source]:
    for number, source in enumerate(sources, start=1):
        source.number = number
    return sources


def sources_for_prompt(sources: list[Source]) -> str:
    """The evidence as the answering model sees it: numbered, with where it comes from."""
    blocks = []
    for source in sources:
        where = source.context.label if source.context else "Component-level check"
        if source.page_start:
            where += f", page {source.page_start}" + (f"-{source.page_end}" if source.page_end != source.page_start else "")
        blocks.append(f"[{source.number}] ({source.kind}) {where}\n{source.text}")
    return "\n\n".join(blocks)