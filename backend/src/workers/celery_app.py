from celery import Celery
from celery.signals import worker_process_init

from src.config.settings import get_settings
from src.config.database import engine

# Task names are plain strings so the API can queue a job by name without
# importing the pipeline (and with it PyMuPDF, OpenCV and Tesseract).
PROCESS_VENDOR_FILE_TASK = "process_vendor_file"

celery_app = Celery(
    "doc_checker",
    broker=str(get_settings().redis_url),
    # Modules the worker imports at start-up, so it knows their tasks.
    include=["src.workers.pipeline"],
)

celery_app.conf.update(
    # Remove a job from the queue only after it finishes, not when it starts.
    # If the worker crashes mid-file, Redis hands the job out again.
    task_acks_late=True,
    # Each worker process takes one job at a time. Files take minutes; grabbing
    # several in advance would leave other workers idle while these wait.
    worker_prefetch_multiplier=1,
    # Job status lives in vendor_files.processing_state, so Celery's own
    # result storage isn't needed.
    task_ignore_result=True,
)


@worker_process_init.connect
def reset_database_pool(**_: object) -> None:
    """Give each worker process its own database connections.

    Celery starts one parent process, then copies it ("forks") into several
    workers. Copied connections would be shared by processes that don't know
    about each other, which corrupts traffic. dispose(close=False) drops the
    copied connections without closing the parent's, so each child opens fresh ones.
    """
    engine.dispose(close=False)