import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, enum_check, string_enum


class ReviewItemKind(StrEnum):
    PAGE_TEXT = "page_text"  # low-confidence OCR or handwriting
    SEGMENT_BOUNDARY = "segment_boundary"
    DOCUMENT_TYPE = "document_type"  # low-confidence type or uncertain new type name
    DATE = "date"  # low confidence, ambiguous, or conflicting
    ATTRIBUTE_VALUE = "attribute_value"
    ATTRIBUTE_MAPPING = "attribute_mapping"  # "is 'Latex-free' the same as 'NRL'?"
    COMPLIANCE_STATUS = "compliance_status"


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReviewResolution(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    NOT_APPLICABLE = "not_applicable"


class ReviewItem(Base):
    """One uncertain result routed to a person (Feature 8).

    Resolving it updates this row in place (open -> resolved). The before/after
    values of the corrected record live only in audit_events.
    """

    __tablename__ = "review_items"
    __table_args__ = (
        # Open = no decision recorded yet. Resolved = the full decision is recorded
        # and signed. Nothing in between.
        CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND resolved_by_id IS NULL"
            " AND resolved_at IS NULL AND signature_id IS NULL)"
            " OR (status = 'resolved' AND resolution IS NOT NULL AND resolved_by_id IS NOT NULL"
            " AND resolved_at IS NOT NULL AND signature_id IS NOT NULL)",
            name="resolution_matches_status",
        ),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        enum_check("item_kind", ReviewItemKind),
        enum_check("status", ReviewStatus),
        enum_check("resolution", ReviewResolution),
        # Re-running a pipeline stage can't queue the same question twice.
        # Partial index: only rows that are still open are covered.
        Index(
            "uq_review_items_open_target",
            "target_table",
            "target_record_id",
            "item_kind",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    # --- Where to show it: the reviewer sees the source page next to the value ---
    vendor_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_files.id", ondelete="RESTRICT"), index=True
    )
    # Empty for page-level items found before the file was split into documents.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    page_number: Mapped[int | None]

    # --- What needs judgment ---
    item_kind: Mapped[ReviewItemKind] = mapped_column(string_enum(ReviewItemKind))
    # The record being reviewed. Not a foreign key, because it can be in any of
    # several tables (pages, documents, document_dates, ...).
    target_table: Mapped[str]
    target_record_id: Mapped[uuid.UUID]
    # Why it was routed here, e.g. "OCR confidence 0.61 is below 0.80".
    reason: Mapped[str] = mapped_column(Text)

    # --- The decision ---
    status: Mapped[ReviewStatus] = mapped_column(
        string_enum(ReviewStatus),
        default=ReviewStatus.OPEN,
        server_default=ReviewStatus.OPEN.value,
        index=True,
    )
    resolution: Mapped[ReviewResolution | None] = mapped_column(string_enum(ReviewResolution))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None]
    # Each decision has its own signature; one signature can't resolve two items.
    signature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("electronic_signatures.id", ondelete="RESTRICT"), unique=True
    )