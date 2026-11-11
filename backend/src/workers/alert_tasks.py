import logging
from datetime import UTC, datetime

from src.config.database import SessionLocal
from src.review.follow_up import follow_up_alerts
from src.review.sending import send_digests, send_immediate_emails
from src.workers.celery_app import (
    FOLLOW_UP_ALERTS_TASK,
    SEND_ALERT_DIGESTS_TASK,
    SEND_ALERT_EMAILS_TASK,
    celery_app,
)

logger = logging.getLogger(__name__)


@celery_app.task(name=FOLLOW_UP_ALERTS_TASK)
def follow_up_alerts_task() -> None:
    """Queue reminders and escalations for unacknowledged alerts (hourly)."""
    with SessionLocal() as session:
        counts = follow_up_alerts(session, datetime.now(UTC))
        session.commit()
    logger.info("Alert follow-up: %(reminders)d reminder(s), %(escalations)d escalation(s).", counts)


@celery_app.task(name=SEND_ALERT_EMAILS_TASK)
def send_alert_emails_task() -> None:
    """Send pending immediate emails: critical alerts and escalations (every 5 minutes)."""
    with SessionLocal() as session:
        counts = send_immediate_emails(session, datetime.now(UTC))
    if counts["sent"] or counts["failed"]:
        logger.info("Alert emails: %(sent)d sent, %(failed)d failed.", counts)


@celery_app.task(name=SEND_ALERT_DIGESTS_TASK)
def send_alert_digests_task() -> None:
    """Send each person's summary of non-urgent alerts (daily, 07:00 UTC)."""
    with SessionLocal() as session:
        counts = send_digests(session, datetime.now(UTC))
    logger.info("Alert digests: %(emails)d email(s), %(items)d item(s), %(failed)d failed.", counts)

