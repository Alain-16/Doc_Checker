import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, EMPTY_JSONB,EMPTY_TEXT_ARRAY, string_enum

if TYPE_CHECKING:
    from src.models.compliance import ComplianceAttribute, ComplianceFinding
    from src.models.vendor_file import VendorFile


class DocumentTypeOrigin(StrEnum):
    """Where the document came from, for traceability and compliance."""

    SEEDED = "seeded"
    DISCOVERED = "discovered"


class ComplianceStatus(StrEnum):

    CURRENT = "current"
    APPROACHING_REVIEW = "approaching_review"
    STALE = "stale"
    NEEDS_REVIEW = "needs_review"


class ResultMethod(StrEnum):

    RULES = "rules"
    LLM = "llm"
    HUMAN = "human"

class DateType(StrEnum):
    MANUFACTURING = "manufacturing"
    EFFECTIVE = "effective"
    SIGNATURE = "signature"
    REVISION = "revision"
    ISSUE = "issue"
    EXPIRY = "expiry"
    OTHER = "other"


class DatePrecision(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"



class DocumentType(Base):

    __tablename__ = "document_types"

    name: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    description: Mapped[str] = mapped_column(Text) 
    origin: Mapped[DocumentTypeOrigin] = mapped_column(
        string_enum(DocumentTypeOrigin),
        default=DocumentTypeOrigin.DISCOVERED,
        server_default=DocumentTypeOrigin.DISCOVERED.value,
    )
    aliases: Mapped[list[str]] = mapped_column(default=list, server_default=EMPTY_TEXT_ARRAY)
    documents: Mapped[list["Document"]] = relationship(back_populates="document_type")



class Document(Base):

        __tablename__ = "documents"
        __table_args__ = (
        # Two documents in the same file can't start on the same page.
        # Also indexes vendor_file_id.
        UniqueConstraint("vendor_file_id", "start_page"),
        CheckConstraint("start_page >= 1 AND start_page <= end_page", name="page_range_valid"),
        CheckConstraint(
            "segmentation_confidence BETWEEN 0 AND 1", name="segmentation_confidence_range"
        ),
        CheckConstraint(
            "classification_confidence BETWEEN 0 AND 1",
            name="classification_confidence_range",
        ),
    )

        vendor_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_files.id", ondelete="RESTRICT")
    )

        # --- Segmentation (Feature 3) ---
        start_page: Mapped[int]
        end_page: Mapped[int]
        segmentation_confidence: Mapped[float]
        # Why the boundary was placed here, e.g. {"signals": ["title", "page_counter_reset"]}.
        segmentation_evidence: Mapped[dict[str, Any]] = mapped_column(
            default=dict, server_default=EMPTY_JSONB
        )

        # --- Classification (Feature 4) ---
        # Empty until classification runs, since segmentation creates the row first.
        document_type_id: Mapped[uuid.UUID | None] = mapped_column(
            ForeignKey("document_types.id", ondelete="RESTRICT"), index=True
        )
        classification_method: Mapped[ResultMethod | None] = mapped_column(string_enum(ResultMethod))
        # Which GPT model classified it, when GPT was used, e.g. "gpt-5-mini".
        classification_model: Mapped[str | None]
        classification_confidence: Mapped[float | None]

    # --- Identity read from the document ---
        title: Mapped[str | None]
        document_number: Mapped[str | None]
        revision: Mapped[str | None]

        # --- Compliance status (Feature 7) ---
        # Copied here from the latest finding because the dashboard reads it constantly.
        governing_date: Mapped[date | None]
        # Starts as needs_review: nothing looks "fine" until the rules engine has checked it.
        compliance_status: Mapped[ComplianceStatus] = mapped_column(
            string_enum(ComplianceStatus),
            default=ComplianceStatus.NEEDS_REVIEW,
            server_default=ComplianceStatus.NEEDS_REVIEW.value,
            index=True,
        )
        status_reason: Mapped[str | None] = mapped_column(Text)
        status_evaluated_at: Mapped[datetime | None]

        # Type-specific facts without their own column, e.g. {"storage_conditions": "..."}.
        extracted_fields: Mapped[dict[str, Any]] = mapped_column(
            default=dict, server_default=EMPTY_JSONB
        )

        vendor_file: Mapped["VendorFile"] = relationship(back_populates="documents")
        document_type: Mapped[DocumentType | None] = relationship(back_populates="documents")
        dates: Mapped[list["DocumentDate"]] = relationship(back_populates="document")
        attributes: Mapped[list["ComplianceAttribute"]] = relationship(back_populates="document")
        findings: Mapped[list["ComplianceFinding"]] = relationship(back_populates="document")


class DocumentDate(Base):
    """One date found in a document, normalized, typed, and traced to its page."""

    __tablename__ = "document_dates"
    __table_args__ = (
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    date_type: Mapped[DateType] = mapped_column(string_enum(DateType))

    # Partial dates use the earliest possible day ("2003-10" -> 2003-10-01) and
    # `precision` records that the day isn't real. The original text is kept as well.
    date_value: Mapped[date]
    precision: Mapped[DatePrecision] = mapped_column(string_enum(DatePrecision))
    original_text: Mapped[str]

    # True = describes this document. False = merely mentioned by it
    # ("supersedes Rev. 10 (2019)"), so the rules engine ignores it.
    is_document_date: Mapped[bool]
    # e.g. "05/06/2022": May 6 or June 5? Flagged for review instead of guessed.
    is_ambiguous: Mapped[bool] = mapped_column(default=False, server_default=false())

    page_number: Mapped[int]
    evidence_snippet: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[ResultMethod] = mapped_column(string_enum(ResultMethod))
    confidence: Mapped[float]

    document: Mapped[Document] = relationship(back_populates="dates")