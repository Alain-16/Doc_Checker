import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import EMPTY_JSONB, Base, enum_check, string_enum
from src.models.compliance import FindingSeverity
from src.models.user import UserRole

class AlertEvent(StrEnum):
    """What can raise an alert. Each has exactly one policy (alert_policies)."""

    FINDING = "finding"  # a compliance finding opened or got worse
    COMING_DUE = "coming_due"  # a document's review falls due soon
    REVIEW_OVERDUE = "review_overdue"  # review items left open too long


class AlertStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"  # someone has seen it and is on it
    RESOLVED = "resolved"  # the cause went away; set by the system, never by a click


class DeliveryKind(StrEnum):
    INITIAL = "initial"
    REMINDER = "reminder"
    ESCALATION = "escalation"


class DeliveryChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"  # Phase B


class DeliveryStatus(StrEnum):
    # Phase A has no users yet, so nothing can be sent: deliveries wait here.
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"



class AlertPolicy(Base):

    __tablename__ = "alert_policies"
    __table_args__= (
        UniqueConstraint("event","version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("reminder_days > 0", name="reminder_days_positive"),
        CheckConstraint(
            "escalate_critical_after_days > 0 AND escalate_after_days > 0", name="escalation_days_positive"
        ),
        enum_check("event", AlertEvent),
        enum_check("audience_role", UserRole),
    )

    event: Mapped[AlertEvent] = mapped_column(string_enum(AlertEvent))
    version: Mapped[int]
    enabled: Mapped[bool]
    audience_role: Mapped[UserRole] = mapped_column(string_enum(UserRole))
    reminder_days: Mapped[int]
    escalate_critical_after_days: Mapped[int]
    escalate_after_days: Mapped[int]
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSONB)
    change_reason: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id",ondelete="RESTRICT"))
    signature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("electronic_signatures.id",ondelete="RESTRICT")
    ) 

class Alert(Base):
    """One thing that needs a person's attention, from raised to resolved."""

    __tablename__ = "alerts"
    __table_args__ = (
        # One live alert per cause: re-running the checks never duplicates it.
        # Resolved alerts are history, so the same cause can be raised again later.
        Index("uq_alerts_live_dedup_key", "dedup_key", unique=True, postgresql_where=text("status <> 'resolved'")),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="resolved_fields_together"
        ),
        CheckConstraint("status <> 'acknowledged' OR acknowledged_at IS NOT NULL", name="acknowledged_has_time"),
        CheckConstraint("reminder_count >= 0", name="reminder_count_not_negative"),
        enum_check("event", AlertEvent),
        enum_check("status", AlertStatus),
        enum_check("severity", FindingSeverity),
        enum_check("audience_role", UserRole),
    )

    event: Mapped[AlertEvent] = mapped_column(string_enum(AlertEvent))
    # What the alert is about, as a stable text key, e.g. "finding:<id>" or
    # "coming_due:<document id>:2025-06-30". The same cause always gives the same key.
    dedup_key: Mapped[str]
    severity: Mapped[FindingSeverity] = mapped_column(string_enum(FindingSeverity))
    status: Mapped[AlertStatus] = mapped_column(
        string_enum(AlertStatus), default=AlertStatus.OPEN, server_default=AlertStatus.OPEN.value, index=True
    )
    title: Mapped[str]
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=EMPTY_JSONB)
    audience_role: Mapped[UserRole] = mapped_column(string_enum(UserRole))
    # The policy version that raised it, so its reminder and escalation timing is traceable.
    policy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_policies.id", ondelete="RESTRICT"))

    # --- What it is about (any that apply) ---
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    component_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("components.id", ondelete="RESTRICT"), index=True)
    vendor_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendor_files.id", ondelete="RESTRICT"))
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compliance_findings.id", ondelete="RESTRICT"), index=True
    )

    # --- Follow-up ---
    last_notified_at: Mapped[datetime]
    reminder_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    escalated_at: Mapped[datetime | None]

    # --- Acknowledgement (who: Feature 14) ---
    acknowledged_at: Mapped[datetime | None]
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    acknowledgement_note: Mapped[str | None] = mapped_column(Text)

    # --- Resolution ---
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None] = mapped_column(Text)  # why it closed, e.g. "The finding was resolved."

    policy: Mapped[AlertPolicy] = relationship()
    deliveries: Mapped[list["AlertDelivery"]] = relationship(
        back_populates="alert", order_by="AlertDelivery.created_at"
    )


class AlertDelivery(Base):
    """One attempt to tell someone about an alert: the proof that people were told."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        enum_check("kind", DeliveryKind),
        enum_check("channel", DeliveryChannel),
        enum_check("status", DeliveryStatus),
        enum_check("audience_role", UserRole),
    )

    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[DeliveryKind] = mapped_column(string_enum(DeliveryKind))
    channel: Mapped[DeliveryChannel] = mapped_column(string_enum(DeliveryChannel))
    audience_role: Mapped[UserRole] = mapped_column(string_enum(UserRole))
    # The person it went to. Empty in Phase A: recipients are resolved in Phase B.
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[DeliveryStatus] = mapped_column(
        string_enum(DeliveryStatus), default=DeliveryStatus.PENDING, server_default=DeliveryStatus.PENDING.value
    )
    sent_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)

    alert: Mapped[Alert] = relationship(back_populates="deliveries")


