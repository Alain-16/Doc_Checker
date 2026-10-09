import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, enum_check, string_enum

# Length of a SHA-256 hash written as hexadecimal text.
SHA256_HEX_LENGTH = 64


class SignatureMeaning(StrEnum):
    """The meanings 21 CFR Part 11 §11.50 lists for a signature."""

    REVIEW = "review"
    APPROVAL = "approval"
    RESPONSIBILITY = "responsibility"
    AUTHORSHIP = "authorship"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"  # the processing pipeline or a scheduled job


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ElectronicSignature(Base):
    """One signature applied by one user to one specific version of one record."""

    __tablename__ = "electronic_signatures"
    __table_args__ = (
        Index("ix_electronic_signatures_record", "record_table", "record_id"),
        enum_check("meaning", SignatureMeaning),
    )

    signer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # A copy of the signer's name at signing time. If their name changes later,
    # the signature must still show the name they signed with.
    signer_name: Mapped[str]
    meaning: Mapped[SignatureMeaning] = mapped_column(string_enum(SignatureMeaning))
    # Set by the database clock. Kept separate from created_at because "signed at"
    # is what an inspector looks for.
    signed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # What was signed. Not a foreign key, because any table can be signed.
    record_table: Mapped[str]
    record_id: Mapped[uuid.UUID]
    # Fingerprint of the record's content when signed. If the record is changed
    # later, its fingerprint no longer matches, so the signature can't be reused.
    record_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    comment: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    """One change to a regulated record: who, when (created_at), what, before/after, why."""

    __tablename__ = "audit_events"
    __table_args__ = (
        # A user action names the user; a system action names nobody.
        CheckConstraint("(actor_type = 'user') = (actor_id IS NOT NULL)", name="actor_matches_type"),
        # Part 11: a person changing or deleting a record must say why.
        CheckConstraint(
            "actor_type = 'system' OR action = 'create' OR reason IS NOT NULL",
            name="user_change_has_reason",
        ),
        # create = only "after", update = both, delete = only "before".
        CheckConstraint(
            "(action = 'create' AND before IS NULL AND after IS NOT NULL)"
            " OR (action = 'update' AND before IS NOT NULL AND after IS NOT NULL)"
            " OR (action = 'delete' AND before IS NOT NULL AND after IS NULL)",
            name="values_match_action",
        ),
        # "Show the full history of this record" is the most common audit question.
        Index("ix_audit_events_record", "table_name", "record_id"),
        Index("ix_audit_events_created_at", "created_at"),
        enum_check("actor_type", ActorType),
        enum_check("action", AuditAction),
    )

    actor_type: Mapped[ActorType] = mapped_column(string_enum(ActorType))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[AuditAction] = mapped_column(string_enum(AuditAction))

    # Which record changed. Not a foreign key, because any table can be audited.
    table_name: Mapped[str]
    record_id: Mapped[uuid.UUID]
    # The record's values before and after the change.
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    reason: Mapped[str | None] = mapped_column(Text)

    # Set when the change required a signature (review decisions, policy changes, deletions).
    signature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("electronic_signatures.id", ondelete="RESTRICT")
    )