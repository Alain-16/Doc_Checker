import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, false, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import EMPTY_JSONB, EMPTY_TEXT_ARRAY, Base, enum_check, string_enum
from src.models.document import ComplianceStatus, Document, DocumentType, ResultMethod


class AttributeGroup(StrEnum):
    """Why an attribute is extracted, which decides where in the document it is looked for."""

    # Document control data, for every document: read from its control pages
    # (first pages + last page), where title blocks, revisions and signatures are.
    CORE = "core"
    # Critical fields of one document type (a certificate's lots): control pages too.
    TYPE_SPECIFIC = "type_specific"
    # Chosen by QA, e.g. latex status: can be anywhere, so found by index search.
    PRIORITY = "priority"


class AttributeValueType(StrEnum):
    TEXT = "text"
    TEXT_LIST = "text_list"  # e.g. every item number the document covers
    DATE = "date"  # stored as "YYYY-MM-DD"
    STATUS = "status"  # one of StatusValue
    RECORDS = "records"  # rows of named fields, e.g. lot number + manufacturing date


class StatusValue(StrEnum):
    YES = "yes"
    NO = "no"
    CONDITIONAL = "conditional"  # true only under conditions the document states


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RuleKind(StrEnum):
    """The checks the engine knows (Feature 7). Each is validated code in
    src/compliance/rule_kinds.py; QA configures rules as instances of these."""

    DOCUMENT_AGE = "document_age"
    MISSING_FIELD = "missing_field"
    RECORD_COMPLETENESS = "record_completeness"
    DATE_CONFLICT = "date_conflict"
    LOW_CONFIDENCE = "low_confidence"
    # Component-level: about what a component's documents are, not one document.
    MISSING_DOCUMENT = "missing_document"
    REVISION_WITHOUT_REPLACEMENT = "revision_without_replacement"


class KeyAttribute(Base):
    """One attribute the system extracts: the configured list QA maintains (Feature 6).

    Only what QA checks on every document is extracted; everything else stays
    in the document and is answered by search (the compliance assistant).
    Seeded by migration for now; QA edits it once users and signatures exist (F14).
    """

    __tablename__ = "key_attributes"
    __table_args__ = (
        # Core applies to every type, type-specific to exactly one; priority to either.
        CheckConstraint(
            "attribute_group = 'priority' OR (attribute_group = 'core') = (document_type_id IS NULL)",
            name="group_matches_document_type",
        ),
        # A priority attribute is found by searching the index, so it needs a query.
        CheckConstraint(
            "attribute_group <> 'priority' OR search_query IS NOT NULL", name="priority_has_search_query"
        ),
        CheckConstraint(
            "(value_type = 'records') = (cardinality(record_fields) > 0)", name="records_have_fields"
        ),
        enum_check("attribute_group", AttributeGroup),
        enum_check("value_type", AttributeValueType),
    )

    # Stable key, also the field name GPT fills in, e.g. "revision".
    name: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    # Tells GPT exactly what to look for: this is the extraction instruction.
    description: Mapped[str] = mapped_column(Text)
    attribute_group: Mapped[AttributeGroup] = mapped_column(string_enum(AttributeGroup))
    value_type: Mapped[AttributeValueType] = mapped_column(string_enum(AttributeValueType))
    # Empty = every document type.
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_types.id", ondelete="RESTRICT"), index=True
    )
    # For records only: the fields of one row, e.g. ["lot_number", "manufacturing_date"].
    record_fields: Mapped[list[str]] = mapped_column(default=list, server_default=EMPTY_TEXT_ARRAY)
    # For priority attributes: what to search the document's chunks for.
    search_query: Mapped[str | None]
    # Required = a document that doesn't state it gets a "not stated" row, itself a finding.
    required: Mapped[bool] = mapped_column(default=False, server_default=false())
    active: Mapped[bool] = mapped_column(default=True, server_default=true())

    values: Mapped[list["DocumentAttribute"]] = relationship(back_populates="key_attribute")


class DocumentAttribute(Base):
    """The value of one key attribute in one document, with its evidence."""

    __tablename__ = "document_attributes"
    __table_args__ = (
        UniqueConstraint("document_id", "key_attribute_id"),
        # Every stated value must point to its evidence. Only "not stated"
        # (value IS NULL) may lack a page and snippet: there's nothing to cite.
        CheckConstraint(
            "value IS NULL OR (page_number IS NOT NULL AND evidence_snippet IS NOT NULL)",
            name="stated_value_has_evidence",
        ),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        enum_check("extraction_method", ResultMethod),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"))
    key_attribute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("key_attributes.id", ondelete="RESTRICT"), index=True
    )
    # Shape depends on the attribute's value_type: "11", ["4432/50 Grey"], "2009-11-23",
    # "yes", or [{"lot_number": "...", "manufacturing_date": "..."}].
    # NULL = not stated. none_as_null stores Python None as SQL NULL, not JSON null.
    value: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)

    page_number: Mapped[int | None]
    evidence_snippet: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[ResultMethod] = mapped_column(string_enum(ResultMethod))
    confidence: Mapped[float]

    document: Mapped[Document] = relationship(back_populates="attributes")
    key_attribute: Mapped[KeyAttribute] = relationship(back_populates="values")


class ComplianceRule(Base):
    """A configured rule: which check, for which document type. Its settings live in versions.

    The rule row never changes after creation; every edit adds a version, so the
    rules in force on any past date can always be shown (Part 11).
    """

    __tablename__ = "compliance_rules"
    __table_args__ = (enum_check("kind", RuleKind),)

    # Stable name used in findings and messages, e.g. "COMPLIANCE_BULLETIN_AGE".
    code: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[RuleKind] = mapped_column(string_enum(RuleKind))
    # Empty = every document type (and always empty for component-level kinds).
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_types.id", ondelete="RESTRICT"), index=True
    )

    document_type: Mapped["DocumentType | None"] = relationship()
    versions: Mapped[list["ComplianceRuleVersion"]] = relationship(
        back_populates="rule", order_by="ComplianceRuleVersion.version"
    )

    @property
    def current(self) -> "ComplianceRuleVersion":
        return self.versions[-1]


class ComplianceRuleVersion(Base):
    """One version of a rule's settings. Append-only: a database trigger blocks UPDATE and DELETE."""

    __tablename__ = "compliance_rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        enum_check("severity", FindingSeverity),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("compliance_rules.id", ondelete="RESTRICT"))
    version: Mapped[int]
    name: Mapped[str]
    # The kind's settings, checked against its parameter model before saving,
    # e.g. {"governing_date_types": ["signature"], "threshold_months": 36, "warning_months": 6}.
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSONB)
    severity: Mapped[FindingSeverity] = mapped_column(string_enum(FindingSeverity))
    active: Mapped[bool]
    # Why this version exists. Required: the audit trail must say why a rule changed.
    change_reason: Mapped[str] = mapped_column(Text)
    # Who made the change. Empty until users exist (Feature 14); then required.
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    rule: Mapped[ComplianceRule] = relationship(back_populates="versions")


class ComplianceFinding(Base):
    """A conclusion of the rules engine about one document or one component (Feature 7).

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
            postgresql_where=text("NOT resolved AND document_id IS NOT NULL"),
        ),
        Index(
            "uq_compliance_findings_open_component_rule",
            "component_id",
            "rule_code",
            unique=True,
            postgresql_where=text("NOT resolved AND component_id IS NOT NULL"),
        ),
        # About exactly one thing: a document, or a component as a whole
        # ("no Quality Certificate" isn't about any one document).
        CheckConstraint("(document_id IS NULL) <> (component_id IS NULL)", name="one_subject"),
        CheckConstraint("resolved = (resolved_at IS NOT NULL)", name="resolved_fields_together"),
        enum_check("status", ComplianceStatus),
        enum_check("severity", FindingSeverity),
    )

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="RESTRICT"), index=True
    )
    # Which rule produced this, e.g. "TECHNICAL_SUPPORT_BULLETIN_AGE".
    rule_code: Mapped[str]
    # The exact rule settings that produced it.
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_rule_versions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[ComplianceStatus] = mapped_column(string_enum(ComplianceStatus))
    severity: Mapped[FindingSeverity] = mapped_column(string_enum(FindingSeverity))
    # One-sentence explanation shown to the user (Feature 7).
    message: Mapped[str] = mapped_column(Text)
    # The facts behind the decision, e.g. {"date_id": "...", "issue_date": "2009-11-23", "page": 24}.
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSONB)
    governing_date: Mapped[date | None]
    last_evaluated_at: Mapped[datetime]

    resolved: Mapped[bool] = mapped_column(default=False, server_default=false())
    resolved_at: Mapped[datetime | None]

    document: Mapped[Document | None] = relationship(back_populates="findings")
    rule_version: Mapped[ComplianceRuleVersion] = relationship()