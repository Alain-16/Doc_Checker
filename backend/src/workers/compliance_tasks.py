import logging

from src.compliance.evaluation import evaluate_everything
from src.config.database import SessionLocal
from src.workers.celery_app import EVALUATE_ALL_COMPLIANCE_TASK, celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name=EVALUATE_ALL_COMPLIANCE_TASK)
def evaluate_all_compliance() -> None:
    """Re-judge every document and component: nightly, and after any rule change."""
    with SessionLocal() as session:
        count = evaluate_everything(session)
        session.commit()
    logger.info("Compliance re-evaluated for %d documents.", count)
