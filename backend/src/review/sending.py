"""Sending alert emails: immediate ones (critical, escalations) and each person's digest.

Each email is committed as soon as it is sent, so a crash halfway never
sends the same email twice. A failed send is retried on the next run, up to
MAX_SEND_ATTEMPTS, then recorded as failed with the error.
"""

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.auth.email import send_email
from src.config.settings import get_settings
from src.models import Alert, AlertDelivery, User
from src.models.alert import DeliveryChannel, DeliveryKind, DeliveryStatus
from src.models.user import DigestFrequency

logger = logging.getLogger(__name__)

MAX_SEND_ATTEMPTS = 5
WEEKLY_DIGEST_WEEKDAY = 0  # Monday (datetime.weekday(): Monday = 0)
KIND_LABELS = {
    DeliveryKind.INITIAL: "New alert",
    DeliveryKind.REMINDER: "Reminder: still open",
    DeliveryKind.ESCALATION: "ESCALATED: not acknowledged in time",
}


def alert_link(alert: Alert) -> str:
    return f"{str(get_settings().app_base_url).rstrip('/')}/alerts/{alert.id}"


def alert_lines(alert: Alert, kind: DeliveryKind) -> str:
    """How one alert reads in an email."""
    return (
        f"[{alert.severity.value.upper()}] {KIND_LABELS[kind]}\n"
        f"{alert.title}\n{alert.message}\n{alert_link(alert)}"
    )


def record_failure(delivery: AlertDelivery, error: Exception) -> None:
    delivery.attempts += 1
    delivery.error = f"{type(error).__name__}: {error}"
    if delivery.attempts >= MAX_SEND_ATTEMPTS:
        delivery.status = DeliveryStatus.FAILED


def send_immediate_emails(session: Session, now: datetime) -> dict[str, int]:
    """Send every pending immediate email (critical alerts and escalations)."""
    counts = {"sent": 0, "failed": 0}
    deliveries = session.scalars(
        select(AlertDelivery)
        .where(AlertDelivery.channel == DeliveryChannel.EMAIL, AlertDelivery.status == DeliveryStatus.PENDING)
        .options(selectinload(AlertDelivery.alert), selectinload(AlertDelivery.recipient))
        .order_by(AlertDelivery.created_at)
    ).all()
    for delivery in deliveries:
        alert = delivery.alert
        try:
            send_email(
                delivery.recipient.email,
                f"[Doc Checker] {KIND_LABELS[delivery.kind]}: {alert.title}",
                f"Hello {delivery.recipient.full_name},\n\n{alert_lines(alert, delivery.kind)}\n",
            )
        except Exception as error:  # any sending problem: record it, retry next run
            logger.warning("Alert email to %s failed: %s", delivery.recipient.email, error)
            record_failure(delivery, error)
            counts["failed"] += 1
        else:
            delivery.status, delivery.sent_at = DeliveryStatus.SENT, now
            counts["sent"] += 1
        session.commit()
    return counts


def send_digests(session: Session, now: datetime) -> dict[str, int]:
    """One summary email per person with pending digest items (weekly people: Mondays only)."""
    counts = {"emails": 0, "items": 0, "failed": 0}
    pending = session.scalars(
        select(AlertDelivery)
        .where(AlertDelivery.channel == DeliveryChannel.DIGEST, AlertDelivery.status == DeliveryStatus.PENDING)
        .options(selectinload(AlertDelivery.alert), selectinload(AlertDelivery.recipient))
        .order_by(AlertDelivery.created_at)
    ).all()
    by_person: dict[User, list[AlertDelivery]] = defaultdict(list)
    for delivery in pending:
        by_person[delivery.recipient].append(delivery)

    for person, deliveries in by_person.items():
        if person.digest_frequency == DigestFrequency.WEEKLY and now.weekday() != WEEKLY_DIGEST_WEEKDAY:
            continue  # they accumulate until Monday
        # The same alert can be pending twice (raised, then reminded): show it once, latest news first.
        latest: dict = {}
        for delivery in reversed(deliveries):
            latest.setdefault(delivery.alert_id, delivery)
        items = sorted(latest.values(), key=lambda d: (d.alert.severity != "critical", d.alert.title))
        body = "\n\n".join(alert_lines(d.alert, d.kind) for d in items)
        try:
            send_email(
                person.email,
                f"[Doc Checker] Your {person.digest_frequency.value} alert summary: {len(items)} item(s)",
                f"Hello {person.full_name},\n\nThese alerts need your attention:\n\n{body}\n",
            )
        except Exception as error:
            logger.warning("Digest to %s failed: %s", person.email, error)
            for delivery in deliveries:
                record_failure(delivery, error)
            counts["failed"] += 1
        else:
            for delivery in deliveries:  # every row it summarised counts as delivered
                delivery.status, delivery.sent_at = DeliveryStatus.SENT, now
            counts["emails"] += 1
            counts["items"] += len(items)
        session.commit()
    return counts
