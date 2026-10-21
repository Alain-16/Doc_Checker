import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.database import get_session
from src.ingestion.storage import open_original
from src.ingestion.upload import DuplicateUpload, register_upload
from src.ingestion.upload_checks import UploadRejected
from src.models import VendorFile
from src.models.vendor_file import ProcessingStatus
from src.workers.celery_app import PROCESS_VENDOR_FILE_TASK, celery_app

router = APIRouter(prefix="/vendor-files", tags=["vendor files"])


class UploadAccepted(BaseModel):
    vendor_file_id: uuid.UUID
    status: ProcessingStatus


class ProcessingStatusOut(BaseModel):
    vendor_file_id: uuid.UUID
    filename: str
    page_count: int
    status: ProcessingStatus
    # Per-stage progress, e.g. {"read_pages": "completed", "segment": "running"}.
    stages: dict[str, Any]
    error: str | None
    # Empty until the pipeline (or a reviewer) identifies the component.
    component_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None


def queue_processing(vendor_file_id: uuid.UUID) -> None:

    celery_app.send_task(PROCESS_VENDOR_FILE_TASK, args=[str(vendor_file_id)])


def get_vendor_file_or_404(session: Session, vendor_file_id: uuid.UUID) -> VendorFile:
    vendor_file = session.get(VendorFile, vendor_file_id)
    if vendor_file is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Vendor file not found"
        )
    return vendor_file

@router.post("", response_model=UploadAccepted, status_code=status.HTTP_202_ACCEPTED)
def upload_vendor_file(
    file: UploadFile = File(), session: Session = Depends(get_session)
) -> UploadAccepted:

    try:
        vendor_file = register_upload(session, file.file, file.filename or "upload.pdf")
    except UploadRejected as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    except DuplicateUpload as error:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message":"this file was already uploaded", "existing_vendor_file_id": str(error.existing.id)},
        )

    queue_processing(vendor_file.id)
    return UploadAccepted(vendor_file_id=vendor_file.id, status=vendor_file.processing_status)


@router.get("/{vendor_file_id}/status", response_model=ProcessingStatusOut)
def get_processing_status(
    vendor_file_id: uuid.UUID, session: Session = Depends(get_session)
) -> ProcessingStatusOut:
    vendor_file = get_vendor_file_or_404(session, vendor_file_id)
    return ProcessingStatusOut(
        vendor_file_id=vendor_file.id,
        filename=vendor_file.filename,
        page_count=vendor_file.page_count,
        status=vendor_file.processing_status,
        stages=vendor_file.processing_state.get("stages", {}),
        error=vendor_file.processing_state.get("error"),
        component_id=vendor_file.component_id,
        superseded_by_id=vendor_file.superseded_by_id,
    )

@router.post("/{vendor_file_id}/resume", response_model=UploadAccepted, status_code=status.HTTP_202_ACCEPTED)
def resume_processing(vendor_file_id: uuid.UUID, session: Session = Depends(get_session)) -> UploadAccepted:
    """Queue a failed file again. The worker skips the stages already completed."""
    vendor_file = get_vendor_file_or_404(session, vendor_file_id)
    if vendor_file.processing_status != ProcessingStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only failed files can be resumed; this one is {vendor_file.processing_status}.",
        )
    queue_processing(vendor_file.id)
    return UploadAccepted(vendor_file_id=vendor_file.id, status=vendor_file.processing_status)


@router.get("/{vendor_file_id}/original")
def download_original(vendor_file_id: uuid.UUID, session: Session = Depends(get_session)) -> StreamingResponse:
    """Send back the stored original, unchanged (Feature 1)."""
    vendor_file = get_vendor_file_or_404(session, vendor_file_id)
    body = open_original(vendor_file.storage_key)
    # Stream it in pieces rather than loading the whole PDF into memory first.
    return StreamingResponse(
        body.iter_chunks(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{vendor_file.filename}"'},
    )