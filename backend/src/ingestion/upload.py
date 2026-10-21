import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.ingestion.storage import build_storage_key, save_original
from src.ingestion.upload_checks import check_upload
from src.models import VendorFile


class DuplicateUpload(Exception):
    """These file was already uploaded, so the new upload is a duplicate and will be ignored."""

    def __init__(self,existing: VendorFile):
        super().__init__(f"Already uploaded as vendor file {existing.id}")
        self.existing = existing


def find_by_hash(session: Session, file_has:str) -> VendorFile | None:
    return session.scalar(select(VendorFile).where(VendorFile.file_hash == file_hash))

def register_upload(session: Session, source: BinaryIO, filename: str) -> VendorFile:

    with tempfile.TemporaryDirectory() as temp_dir:
        local_path = Path(temp_dir) / "upload.pdf"

        with local_path.open("wb") as local_copy:
            checked = check_upload(source, local_copy, local_path)

        existing = find_by_hash(session, checked.file_hash)
        if existing is not None:
            raise DuplicateUpload(existing)

        vendor_file_id = uuid.uuid4()
        storage_key = build_storage_key(vendor_file_id)
        save_original(local_path,storage_key, checked.file_hash)

    vendor_file = VendorFile(
        id=vendor_file_id,
        filename=filename,
        storage_key=storage_key,
        file_hash=checked.file_hash,
        file_size_bytes=checked.file_size_bytes,
        page_count=checked.page_count,
    )
    session.add(vendor_file)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = find_by_hash(session, checked.file_hash)
        if existing is None:
            raise
        raise DuplicateUpload(existing)
    return vendor_file

