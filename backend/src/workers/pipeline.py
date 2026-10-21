import logging
import uuid
from collections.abc import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.classification.classifier import classify_documents
from src.config.database import SessionLocal
from src.extraction.attributes import extract_attributes
from src.extraction.dates import extract_dates
from src.extraction.missing_attributes import detect_not_stated
from src.ingestion.page_reading import read_pages
from src.ingestion.segmentation import segment_pages
from src.ingestion.superseding import supersede_older_files
from src.models import VendorFile
from src.vendors.identification import identify_vendor
from src.models.vendor_file import ProcessingStatus
from src.workers.celery_app import PROCESS_VENDOR_FILE_TASK, celery_app


logger = logging.getLogger(__name__)

StageFunction = Callable[[Session, VendorFile], None]

# The fixed order of the pipeline. Each stage writes its own rows and leaves
# committing to run_pipeline (except read_pages, which commits page by page).
# The names are what the status endpoint shows.
STAGES: list[tuple[str, StageFunction]] = [
    ("read_pages", read_pages),
    ("segment", segment_pages),
    ("classify", classify_documents),
    ("identify_vendor", identify_vendor),
    ("supersede", supersede_older_files),
    ("extract_dates", extract_dates),
    ("extract_attributes", extract_attributes),
    ("detect_not_stated", detect_not_stated),
]

STAGE_RUNNING = "running"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"

def record_stage(vendor_file: VendorFile, stage: str, state: str, error: str | None = None) -> None:

    stages = dict(vendor_file.processing_state.get("stages", {}))
    stages[stage] = state
    vendor_file.processing_state = {"stages": stages, "error": error}


def claim_vendor_file(session: Session, vendor_file_id: uuid.UUID) -> bool:

    result = session.execute(
        update(VendorFile).where(
            VendorFile.id == vendor_file_id,
            VendorFile.processing_status.in_([ProcessingStatus.QUEUED, ProcessingStatus.FAILED])
        )
        .values(processing_status=ProcessingStatus.RUNNING)
    )
    session.commit()
    return result.rowcount == 1

def run_pipeline(session: Session, vendor_file: VendorFile) -> None:

    for stage_name, run_stage in STAGES:
        if vendor_file.processing_state.get("stages",{}).get(stage_name) == STAGE_COMPLETED:
            continue
        record_stage(vendor_file, stage_name, STAGE_RUNNING)
        session.commit()

        try:
            run_stage(session, vendor_file)
        except Exception as error:
            session.rollback()
            record_stage(vendor_file, stage_name, STAGE_FAILED, error=f"{stage_name}: {error}")
            session.commit()
            raise

        record_stage(vendor_file,stage_name, STAGE_COMPLETED)
        session.commit()

@celery_app.task(name=PROCESS_VENDOR_FILE_TASK)
def process_vendor_file(vendor_file_id: str) -> None:
    """Celery entry point: process one uploaded file (or resume a failed one)."""
    file_id = uuid.UUID(vendor_file_id)
    with SessionLocal() as session:
        if not claim_vendor_file(session, file_id):
            logger.info("Vendor file %s is already running or finished; skipping.", file_id)
            return
        vendor_file = session.get(VendorFile, file_id)
        run_pipeline(session, vendor_file)
