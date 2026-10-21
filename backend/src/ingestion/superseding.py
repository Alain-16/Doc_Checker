from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.models import Component, VendorFile

def supersede_older_files(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: keep exactly one current file per component.

    "Newer" means uploaded later (created_at), not "finished processing later":
    a small file uploaded second can finish before a big file uploaded first,
    and must still be the current one.

    Old rows are never deleted or changed beyond the two superseded_* columns,
    so the audit history stays complete (Feature 1, step 4). Also called later
    by the review queue, once a person identifies an uncertain file's component.
    """
    if vendor_file.component_id is None:
        return  # identification is waiting for review; nothing can be superseded yet

    # Lock the component row: two files of the same component finishing at
    # the same moment take turns here instead of each superseding the other.
    session.get(Component, vendor_file.component_id, with_for_update=True)

    other_current_files = (
        VendorFile.component_id == vendor_file.component_id,
        VendorFile.id != vendor_file.id,
        VendorFile.superseded_by_id.is_(None),
    )

    # --- Was a newer file for this component already processed? Then THIS one is old ---
    newer = session.scalar(
        select(VendorFile)
        .where(*other_current_files, VendorFile.created_at > vendor_file.created_at)
        .order_by(VendorFile.created_at.desc())
        .limit(1)
    )
    if newer is not None:
        vendor_file.superseded_by_id = newer.id
        vendor_file.superseded_at = func.now()
        return

    # --- Otherwise this is the newest: supersede the older current ones ---
    session.execute(
        update(VendorFile)
        .where(*other_current_files, VendorFile.created_at < vendor_file.created_at)
        .values(superseded_by_id=vendor_file.id, superseded_at=func.now())
    )