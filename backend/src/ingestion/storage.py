import uuid
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from src.config.settings import get_settings

ORIGINALS_PREFIX = "originals"
PDF_CONTENT_TYPE = "application/pdf"


@lru_cache
def get_s3_client():
    """Build the S3 client once per process and reuse it.

  
    """
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
        region_name=settings.s3_region,
        aws_access_key_id=(
            settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
        ),
        aws_secret_access_key=(
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None
        ),
    )


def build_storage_key(vendor_file_id: uuid.UUID) -> str:
    """Where a vendor file's original PDF lives, e.g. "originals/<uuid>.pdf".

  
    """
    return f"{ORIGINALS_PREFIX}/{vendor_file_id}.pdf"


def save_original(local_path: Path, storage_key: str, file_hash: str) -> None:
    """Upload a PDF from disk to the originals bucket.


    """
    get_s3_client().upload_file(
        str(local_path),
        get_settings().s3_originals_bucket,
        storage_key,
        ExtraArgs={"ContentType": PDF_CONTENT_TYPE, "Metadata": {"sha256": file_hash}},
    )


def download_original(storage_key: str, destination: Path) -> None:
    """Copy an original PDF from the bucket to a local file (used by the worker)."""
    get_s3_client().download_file(get_settings().s3_originals_bucket, storage_key, str(destination))


def open_original(storage_key: str) -> BinaryIO:
    """Return a readable stream of an original PDF, for sending it to a browser."""
    response = get_s3_client().get_object(
        Bucket=get_settings().s3_originals_bucket, Key=storage_key
    )
    return response["Body"]


def create_originals_bucket() -> None:
    """Create the originals bucket with versioning and Object Lock, then report what stuck.

 
    """
    client = get_s3_client()
    bucket = get_settings().s3_originals_bucket

    # --- Create (Object Lock must be requested now or never) ---
    try:
        client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
        print(f"Created bucket {bucket!r} with Object Lock requested.")
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
        print(f"Bucket {bucket!r} already exists.")

    # --- Versioning: a changed or deleted object keeps its old versions ---
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})

    # --- Report what the storage actually supports ---
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status")
    print(f"Versioning: {versioning}")
    try:
        lock = client.get_object_lock_configuration(Bucket=bucket)
        print(f"Object Lock: {lock['ObjectLockConfiguration'].get('ObjectLockEnabled')}")
    except ClientError as error:
        print(f"Object Lock: NOT available ({error.response['Error']['Code']})")


if __name__ == "__main__":
    create_originals_bucket()