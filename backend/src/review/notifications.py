"""Who is told about an alert, and on which channels: one delivery row per person per channel.

Called whenever an alert is raised, reminded or escalated (raising.py, follow_up.py).
The rows are the record an inspector asks for: "was this person told, and when?".
Sending the emails is a separate job (sending.py); this only decides and records.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Alert, AlertDelivery, Component, Document, OwnerAssignment, User
from src.models.alert import DeliveryChannel, DeliveryKind, DeliveryStatus
from src.models.compliance import FindingSeverity
from src.models.user import DigestFrequency, UserRole

# Escalations always go to every Admin (agreed 2026-10-28).
ESCALATION_ROLE = UserRole.ADMIN


def usable_users():
    """People who can be told: active and not locked (a select to add conditions to)."""
    return select(User).where(User.is_active, User.locked_at.is_(None))


def alert_subject(session: Session, alert: Alert) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """(component id, vendor id) an alert is about, whatever it is attached to."""
    if alert.component_id:
        return alert.component_id, session.get(Component, alert.component_id).vendor_id
    if alert.vendor_id:
        return None, alert.vendor_id
    if alert.document_id:
        document = session.get(Document, alert.document_id)
        return document.component_id, document.vendor_id
    # About a whole file only: it can hold several vendors, so no single owner.
    return None, None


def owners_of(session: Session, component_id: uuid.UUID | None, vendor_id: uuid.UUID | None) -> list[User]:
    """The component's owners; if it has none (or it's a company-level document), its vendor's owners."""
    if component_id is not None:
        component_owners = session.scalars(
            usable_users().join(OwnerAssignment, OwnerAssignment.user_id == User.id)
            .where(OwnerAssignment.component_id == component_id)
        ).all()
        if component_owners:
            return list(component_owners)
    if vendor_id is None:
        return []
    return list(
        session.scalars(
            usable_users().join(OwnerAssignment, OwnerAssignment.user_id == User.id)
            .where(OwnerAssignment.vendor_id == vendor_id)
        )
    )


def recipients(session: Session, alert: Alert, kind: DeliveryKind) -> tuple[list[User], UserRole]:
    """Who is told, and the role that explains why (stored on each delivery)."""
    if kind == DeliveryKind.ESCALATION:
        return list(session.scalars(usable_users().where(User.role == ESCALATION_ROLE))), ESCALATION_ROLE
    owners = owners_of(session, *alert_subject(session, alert))
    if owners:
        return owners, alert.audience_role
    return list(session.scalars(usable_users().where(User.role == alert.audience_role))), alert.audience_role


def notify(session: Session, alert: Alert, kind: DeliveryKind, now: datetime) -> None:
    """Record a notification for everyone who must hear about this alert.

    Each person gets it in their in-app inbox (delivered at once), plus:
    critical alerts and escalations by email right away; the rest in their
    digest, unless they chose no digest. Nobody to tell is recorded too.
    """
    people, role = recipients(session, alert, kind)
    urgent = kind == DeliveryKind.ESCALATION or alert.severity == FindingSeverity.CRITICAL

    if not people:
        alert.deliveries.append(
            AlertDelivery(
                kind=kind, channel=DeliveryChannel.IN_APP, audience_role=role, status=DeliveryStatus.SKIPPED,
                error=f"Nobody to notify: no owner, and no active {role.value.replace('_', ' ')}.",
            )
        )
        return

    for person in people:
        alert.deliveries.append(
            AlertDelivery(
                kind=kind, channel=DeliveryChannel.IN_APP, audience_role=role, recipient_id=person.id,
                status=DeliveryStatus.SENT, sent_at=now,
            )
        )
        if urgent:
            channel = DeliveryChannel.EMAIL
        elif person.digest_frequency != DigestFrequency.NONE:
            channel = DeliveryChannel.DIGEST
        else:
            continue  # in-app only, by the person's choice
        alert.deliveries.append(AlertDelivery(kind=kind, channel=channel, audience_role=role, recipient_id=person.id))
