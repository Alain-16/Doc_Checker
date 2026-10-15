import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pymupdf

MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MB (Feature 1 limit)
MAX_PAGE_COUNT = 500  # Feature 1 limit
# Read and hash the upload 1 MB at a time, so memory use stays flat for any size.
CHUNK_SIZE_BYTES = 1024 * 1024
# The PDF spec allows the "%PDF-" marker anywhere in the first 1024 bytes.
PDF_SIGNATURE = b"%PDF-"
PDF_SIGNATURE_SEARCH_BYTES = 1024


class UploadRejected(Exception):
    """The file can't be accepted. The message is shown to the user as-is."""


@dataclass(frozen=True)
class CheckedPdf:
    """What we learned about an accepted upload."""

    file_hash: str
    file_size_bytes: int
    page_count: int


def copy_and_hash(source: BinaryIO, destination: BinaryIO) -> tuple[str, int]:
    """Copy the upload to a local file while computing its SHA-256 and size.

    Doing both in one pass means the file is read only once. We stop as soon as
    the size limit is passed instead of copying the rest of a huge file.
    """
    sha256 = hashlib.sha256()
    size = 0
    while chunk := source.read(CHUNK_SIZE_BYTES):
        size += len(chunk)
        if size > MAX_FILE_SIZE_BYTES:
            raise UploadRejected(
                f"File is larger than the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit."
            )
        sha256.update(chunk)
        destination.write(chunk)
    destination.flush()
    if size == 0:
        raise UploadRejected("File is empty.")
    return sha256.hexdigest(), size


def check_pdf(path: Path) -> int:
    """Confirm the file is a PDF we can read, and return its page count."""
    # --- Is it a PDF at all? Look at the first bytes, not the filename ---
    with path.open("rb") as file:
        if PDF_SIGNATURE not in file.read(PDF_SIGNATURE_SEARCH_BYTES):
            raise UploadRejected("File is not a PDF.")

    # --- Can we open it? PyMuPDF raises on files too damaged to repair ---
    try:
        document = pymupdf.open(path, filetype="pdf")
    except Exception as error:
        raise UploadRejected(f"PDF is corrupted and can't be opened ({error}).") from error

    with document:
        # needs_pass = a password is needed to read it. (A PDF with only an
        # "owner" password, which blocks printing or editing, can still be read.)
        if document.needs_pass:
            raise UploadRejected("PDF is password-protected. Upload an unprotected copy.")
        if document.page_count == 0:
            raise UploadRejected("PDF has no pages.")
        if document.page_count > MAX_PAGE_COUNT:
            raise UploadRejected(
                f"PDF has {document.page_count} pages; the limit is {MAX_PAGE_COUNT}."
            )
        return document.page_count


def check_upload(source: BinaryIO, local_copy: BinaryIO, local_path: Path) -> CheckedPdf:
    """Run every upload check, leaving a verified copy of the file at local_path."""
    file_hash, file_size_bytes = copy_and_hash(source, local_copy)
    page_count = check_pdf(local_path)
    return CheckedPdf(file_hash=file_hash, file_size_bytes=file_size_bytes, page_count=page_count)