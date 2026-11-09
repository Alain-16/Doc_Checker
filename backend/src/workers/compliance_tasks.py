import logging
import uuid

from sqlalchemy import select

from src.compliance.evaluation import evaluate_everything
from src.config.database import SessionLocal
from src.extraction.key_attributes import documents_missing, fill_in_file
from src.models import KeyAttribute
from src.workers.celery_app import EVALUATE_ALL_COMPLIANCE_TASK, FILL_IN_ATTRIBUTES_TASK, celery_app

logger = logging.getLogger(__name__)

FILL_IN_RETRIES = 3
FILL_IN_RETRY_SECONDS = 300


@celery_app.task(name=EVALUATE_ALL_COMPLIANCE_TASK)
def evaluate_all_compliance() -> None:
    """Re-judge every document and component: nightly, and after any rule change."""
    with SessionLocal() as session:
        count = evaluate_everything(session)
        session.commit()
    logger.info("Compliance re-evaluated for %d documents.", count)


@celery_app.task(name=FILL_IN_ATTRIBUTES_TASK, bind=True, max_retries=FILL_IN_RETRIES)
def fill_in_attributes(self, attribute_ids: list[str]) -> None:
    """Extract newly added attributes from existing documents, then re-judge everything.

    One commit per file, and files already done are skipped on a retry, so a
    failure part-way loses nothing and repeats no GPT calls. Everything is
    re-judged even after a failure: rules were waiting on the files that worked.
    """
    failed = 0
    with SessionLocal() as session:
        ids = [uuid.UUID(attribute_id) for attribute_id in attribute_ids]
        attributes = session.scalars(select(KeyAttribute).where(KeyAttribute.id.in_(ids), KeyAttribute.active)).all()
        for vendor_file_id, documents in documents_missing(session, list(attributes)).items():
            try:
                fill_in_file(session, vendor_file_id, documents, list(attributes))
                session.commit()
            except Exception:
                session.rollback()
                failed += 1
                logger.exception("Filling in attributes failed for vendor file %s.", vendor_file_id)
        evaluate_everything(session)
        session.commit()
    if failed:
        raise self.retry(
            exc=RuntimeError(f"Filling in attributes failed for {failed} file(s)."), countdown=FILL_IN_RETRY_SECONDS
        )
