import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import EMPTY_JSONB, EMPTY_TEXT_ARRAY, Base, string_enum
from src.models.document import ComplianceStatus, Document, ResultMethod


class AttributeStatus(StrEnum):
    YES = "yes"
    NO = "no"
    CONDITIONAL = "conditional"
    # The document doesn't address it at all. Different from "no", and itself a finding.
    NOT_STATED = "not_stated"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class CanonicalAttribute(Base):
    """The growing catalog of normalized compliance attributes (Feature 6)."""

    __tablename__ = "canonical_attributes"

    # Stable key, e.g. "natural_rubber_latex".
    name: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text)
    # Wordings already mapped to this attribute, e.g. ["Latex-free", "NRL"].
    aliases: Mapped[list[str]] = mapped_column(default=list, server_default=EMPTY_TEXT_ARRAY)

    attributes: Mapped[list["ComplianceAttribute"]] = relationship(
        back_populates="canonical_attribute"
    )


class ComplianceAttribute(Base):
    """One compliance claim a document makes, e.g. "Natural rubber latex: not present"."""

    __tablename__ = "compliance_attributes"
    __table_args__ = (
        # Every stated value must point to its evidence. Only "not stated" may
        # lack a page and snippet, because there is nothing on the page to cite.
        CheckConstraint(
            "status = 'not_stated' OR (page_number IS NOT NULL AND evidence_snippet IS NOT NULL)",
            name="stated_value_has_evidence",
        ),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("mapping_confidence BETWEEN 0 AND 1", name="mapping_confidence_range"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    # Empty while an uncertain mapping waits in the review queue.
    canonical_attribute_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("canonical_attributes.id", ondelete="RESTRICT"), index=True
    )
    # The attribute name exactly as the document wrote it, e.g. "Latex-free".
    name_as_written: Mapped[str]
    # The full statement from the document. Empty for "not stated".
    statement: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AttributeStatus] = mapped_column(string_enum(AttributeStatus))

    page_number: Mapped[int | None]
    evidence_snippet: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[ResultMethod] = mapped_column(string_enum(ResultMethod))
    confidence: Mapped[float]
    # How sure we are that name_as_written belongs to the canonical attribute.
    mapping_confidence: Mapped[float | None]

    document: Mapped[Document] = relationship(back_populates="attributes")
    canonical_attribute: Mapped[CanonicalAttribute | None] = relationship(
        back_populates="attributes"
    )


class ComplianceFinding(Base):
    """A conclusion of the rules engine about one document (Feature 7).

    History is kept: when a later evaluation changes the outcome, the old finding is
    marked resolved and a new one is added. A run that changes nothing only updates
    last_evaluated_at. created_at (from Base) is when the finding was first raised.
    """

    __tablename__ = "compliance_findings"
    __table_args__ = (
        # At most one open finding per document and rule. A partial index only
        # covers rows matching the WHERE clause, so resolved history is unlimited.
        Index(
            "uq_compliance_findings_open_document_rule",
            "document_id",
            "rule_code",
            unique=True,
            postgresql_where=text("NOT resolved"),
        ),
        CheckConstraint("resolved = (resolved_at IS NOT NULL)", name="resolved_fields_together"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    # Which rule produced this, e.g. "TECHNICAL_BULLETIN_AGE".
    rule_code: Mapped[str]
    status: Mapped[ComplianceStatus] = mapped_column(string_enum(ComplianceStatus))
    severity: Mapped[FindingSeverity] = mapped_column(string_enum(FindingSeverity))
    # One-sentence explanation shown to the user (Feature 7).
    message: Mapped[str] = mapped_column(Text)
    # The facts behind the decision, e.g. {"date_id": "...", "issue_date": "2009-11-23", "page": 24}.
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSONB)
    governing_date: Mapped[date | None]
    # Version of the rule policy used. Becomes a foreign key to rule_policies in Feature 7.
    policy_version: Mapped[int]
    last_evaluated_at: Mapped[datetime]

    resolved: Mapped[bool] = mapped_column(default=False, server_default=false())
    resolved_at: Mapped[datetime | None]

    document: Mapped[Document] = relationship(back_populates="findings")