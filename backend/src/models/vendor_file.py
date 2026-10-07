import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import EMPTY_JSONB, Base, string_enum

if TYPE_CHECKING:
    from src.models.document import Document
    from src.models.vendor import Component

# Length of a SHA-256 hash written as hexadecimal text.
SHA256_HEX_LENGTH = 64


class ProcessingStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PageSourceType(StrEnum):
    DIGITAL = "digital"  # text layer read directly, no OCR
    SCANNED = "scanned"  # image only, read with OCR
    MIXED = "mixed"  # text layer plus scanned regions (signatures, stamps)


class VendorFile(Base):
    """One uploaded bundle PDF. The PDF itself lives in S3; this row describes it.

    created_at (from Base) is the upload time.
    """

    __tablename__ = "vendor_files"
    __table_args__ = (
        # Same file uploaded twice for the same component = duplicate (Feature 1).
        UniqueConstraint("component_id", "file_hash"),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint("page_count >= 1", name="page_count_positive"),
        # Either the file is current (both empty) or superseded (both filled in).
        CheckConstraint(
            "(superseded_by_id IS NULL) = (superseded_at IS NULL)",
            name="superseded_fields_together",
        ),
        CheckConstraint("superseded_by_id <> id", name="not_superseded_by_itself"),
    )

    component_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("components.id", ondelete="RESTRICT")
    )
    filename: Mapped[str]
    # Where the original PDF is stored in S3/object storage. Never the PDF bytes.
    storage_key: Mapped[str] = mapped_column(unique=True)
    file_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    # BigInteger because a normal integer tops out around 2 GB.
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int]

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        string_enum(ProcessingStatus),
        default=ProcessingStatus.QUEUED,
        server_default=ProcessingStatus.QUEUED.value,
    )
    # Progress of each pipeline stage, e.g. {"read_pages": "completed", "segment": "failed"},
    # so a failed job can resume from the stage that failed.
    processing_state: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=EMPTY_JSONB
    )

    # Points to the newer file that replaced this one. The old row is never
    # deleted or overwritten, so auditors can see what was on file and when.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vendor_files.id", ondelete="RESTRICT")
    )
    superseded_at: Mapped[datetime | None]

    component: Mapped["Component"] = relationship(back_populates="vendor_files")
    pages: Mapped[list["Page"]] = relationship(back_populates="vendor_file")
    documents: Mapped[list["Document"]] = relationship(back_populates="vendor_file")


class Page(Base):
    """One page of a vendor file, as text plus layout, whichever engine read it."""

    __tablename__ = "pages"
    __table_args__ = (
        # A page number appears once per file. Also indexes vendor_file_id.
        UniqueConstraint("vendor_file_id", "page_number"),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )

    vendor_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vendor_files.id", ondelete="RESTRICT")
    )
    page_number: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[PageSourceType] = mapped_column(string_enum(PageSourceType))
    # Which engine produced the text, e.g. "pymupdf", "paddleocr", "textract".
    # Free text, because engines are swapped as benchmarks come in (Feature 13).
    extraction_engine: Mapped[str]
    confidence: Mapped[float]
    # Text blocks with positions, tables, image regions: whatever the engine returned.
    layout_data: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=EMPTY_JSONB
    )

    vendor_file: Mapped[VendorFile] = relationship(back_populates="pages")