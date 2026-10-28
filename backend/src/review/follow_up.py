from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.review.policies import current_policies
from src.models import Alert, AlertDelivery
from src.models.alert import AlertStatus, DeliveryChannel, DeliveryKind
from src.models.compliance import FindingSeverity
from src.models.user import UserRole


ESCALATION_ROLE = UserRole.ADMIN


def follow_up_alerts(session: Session, now: datetime) -> dict[str, int]:
    """Escalate or remind every open (unacknowledged) alert that is due for it.

    Uses each event's *current* policy, so when QA changes the timing, alerts
    already open follow the new timing from the next run.
    Returns how many reminders and escalations were queued.
    """
    policies = current_policies(session)
    counts = {"reminders": 0, "escalations": 0}
    alerts = session.scalars(
        select(Alert).where(Alert.status == AlertStatus.OPEN).options(selectinload(Alert.deliveries))
    ).all()
    for alert in alerts:
        policy = policies[alert.event]
        escalate_after = (
            policy.escalate_critical_after_days
            if alert.severity == FindingSeverity.CRITICAL
            else policy.escalate_after_days
        )
        if alert.escalated_at is None and now - alert.created_at >= timedelta(days=escalate_after):
            alert.escalated_at = now
            alert.deliveries.append(
                AlertDelivery(kind=DeliveryKind.ESCALATION, channel=DeliveryChannel.IN_APP, audience_role=ESCALATION_ROLE)
            )
            counts["escalations"] += 1
        elif now - alert.last_notified_at >= timedelta(days=policy.reminder_days):
            alert.reminder_count += 1
            alert.last_notified_at = now
            alert.deliveries.append(
                AlertDelivery(kind=DeliveryKind.REMINDER, channel=DeliveryChannel.IN_APP, audience_role=alert.audience_role)
            )
            counts["reminders"] += 1
    return counts