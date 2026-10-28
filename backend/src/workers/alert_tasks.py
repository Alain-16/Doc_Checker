import logging
from datetime import UTC, datetime

from src.review.follow_up import follow_up_alerts
from src.config.database import SessionLocal
from src.workers.celery_app import FOLLOW_UP_ALERTS_TASK, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name=FOLLOW_UP_ALERTS_TASK)
def follow_up_alerts_task() -> None:
    """Queue reminders and escalations for unacknowledged alerts (hourly)."""
    with SessionLocal() as session:
        counts = follow_up_alerts(session, datetime.now(UTC))
        session.commit()
    logger.info("Alert follow-up: %(reminders)d reminder(s), %(escalations)d escalation(s).", counts)