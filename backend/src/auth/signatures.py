import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.audit.trail import jsonable
from src.auth.login import register_failed_attempt
from src.auth.passwords import password_matches
from src.models import ElectronicSignature, User
from src.models.audit import SignatureMeaning

# Left out of the fingerprint: set by the database after signing, or the link
# to the signature itself (which can't be part of what it signs).
NOT_FINGERPRINTED = frozenset({"created_at", "updated_at", "signature_id"})


class SignatureError(Exception):
    """The signature can't be applied (wrong password, or the account just got locked)."""


def record_fingerprint(record: Any) -> str:
    """SHA-256 of the record's content: its columns as sorted JSON.

    The signature stores this. If the record is ever changed, its fingerprint
    no longer matches, so a signature can't be reused for different content.
    """
    values = {
        attribute.key: jsonable(getattr(record, attribute.key))
        for attribute in inspect(record).mapper.column_attrs
        if attribute.key not in NOT_FINGERPRINTED
    }
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def confirm_signing_password(session: Session, signer: User, password: str, now: datetime) -> None:
    """Part 11 §11.200: signing needs the password again, even when signed in.

    Call this BEFORE building the record to sign: on failure the caller commits
    (so the failed attempt counts towards the lockout) and nothing else is saved.
    """
    if not password_matches(signer.password_hash, password):
        register_failed_attempt(session, signer, now)
        raise SignatureError("Password incorrect: the change was not signed or saved.")


def sign(session: Session, signer: User, meaning: SignatureMeaning, record: Any, comment: str | None) -> ElectronicSignature:
    """Sign a record that is about to be saved, and link it to the signature.

    The record's id and every column must already be set: the fingerprint is
    taken now, before it reaches the database.
    """
    if record.id is None:
        record.id = uuid.uuid4()
    signature = ElectronicSignature(
        id=uuid.uuid4(),
        signer_id=signer.id,
        signer_name=signer.full_name,  # the name as it is today, kept even if it changes later
        meaning=meaning,
        record_table=record.__tablename__,
        record_id=record.id,
        record_hash=record_fingerprint(record),
        comment=comment,
    )
    session.add(signature)
    # Saved now, on its own, so it exists before the record that points to it.
    session.flush()
    record.signature_id = signature.id
    return signature


def signature_still_matches(signature: ElectronicSignature, record: Any) -> bool:
    """True when the record is exactly what was signed (for inspections and audit reports)."""
    return (
        signature.record_table == record.__tablename__
        and signature.record_id == record.id
        and signature.record_hash == record_fingerprint(record)
    )