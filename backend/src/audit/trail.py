import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import event, insert, inspect
from sqlalchemy.orm import Session

from src.models import AuditEvent, User
from src.models.audit import ActorType, AuditAction

# Records the regulations care about. Not here: sessions and tokens (security
# plumbing), chunks (a search index rebuilt from pages), alert deliveries and
# signatures (records of their own), audit_events itself.
REGULATED_TABLES = frozenset({
    "vendors", "components", "vendor_files", "pages", "documents", "document_dates",
    "document_attributes", "key_attributes", "compliance_rules", "compliance_rule_versions",
    "compliance_findings", "alert_policies", "alerts", "review_items", "users",
})
# Never copied into the audit trail, only noted as changed.
SECRET_COLUMNS = frozenset({"password_hash", "mfa_secret_encrypted"})
# Bookkeeping that changes constantly and says nothing about the record.
UNTRACKED_COLUMNS = frozenset({"created_at", "updated_at", "last_login_at", "failed_login_count"})
REDACTED = "[redacted]"

# Keys in Session.info, the per-session dictionary SQLAlchemy offers for this kind of thing.
ACTOR_KEY = "audit_actor_id"
REASON_KEY = "audit_reason"


class MissingAuditReason(RuntimeError):
    """A person changed or deleted a record without saying why (Part 11 requires a reason)."""


def set_actor(session: Session, user: User) -> None:
    """From now on, changes saved through this session are recorded as done by this user."""
    session.info[ACTOR_KEY] = user.id


def set_audit_reason(session: Session, reason: str) -> None:
    session.info[REASON_KEY] = reason


def jsonable(value: Any) -> Any:
    """A column value as something JSON can hold."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def column_values(record: Any) -> dict[str, Any]:
    """Every tracked column of a record (attribute names, e.g. chunk_metadata)."""
    values = {}
    for attribute in inspect(record).mapper.column_attrs:
        if attribute.key in UNTRACKED_COLUMNS:
            continue
        values[attribute.key] = REDACTED if attribute.key in SECRET_COLUMNS else jsonable(getattr(record, attribute.key))
    return values


def changed_values(record: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Before and after values of the tracked columns this flush changed."""
    before, after = {}, {}
    state = inspect(record)
    for attribute in state.mapper.column_attrs:
        if attribute.key in UNTRACKED_COLUMNS:
            continue
        history = state.attrs[attribute.key].history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        secret = attribute.key in SECRET_COLUMNS
        before[attribute.key] = REDACTED if secret else jsonable(old)
        after[attribute.key] = REDACTED if secret else jsonable(new)
    return before, after


@event.listens_for(Session, "after_flush")
def record_changes(session: Session, flush_context: Any) -> None:
    """Runs after every flush (the moment SQLAlchemy sends changes to the database).

    after_flush, not before: new rows have their ids by now, and the old values
    of changed columns are still available. The audit rows are inserted with
    plain SQL on the same connection, so they commit or roll back together
    with the change they describe.
    """
    actor_id = session.info.get(ACTOR_KEY)
    reason = session.info.get(REASON_KEY)
    rows = []

    def add(action: AuditAction, record: Any, before: dict | None, after: dict | None) -> None:
        rows.append({
            "id": uuid.uuid4(),
            "actor_type": ActorType.USER if actor_id else ActorType.SYSTEM,
            "actor_id": actor_id,
            "action": action,
            "table_name": record.__tablename__,
            "record_id": record.id,
            "before": before,
            "after": after,
            "reason": reason,
            # A signed change (rule version, policy version...) points to its signature.
            "signature_id": getattr(record, "signature_id", None),
        })

    for record in session.new:
        if getattr(record, "__tablename__", None) in REGULATED_TABLES:
            add(AuditAction.CREATE, record, None, column_values(record))
    for record in session.dirty:
        if getattr(record, "__tablename__", None) in REGULATED_TABLES:
            before, after = changed_values(record)
            if after:  # dirty can mean "a relationship list changed": no column change, nothing to record
                add(AuditAction.UPDATE, record, before, after)
    for record in session.deleted:
        if getattr(record, "__tablename__", None) in REGULATED_TABLES:
            add(AuditAction.DELETE, record, column_values(record), None)

    if not rows:
        return
    if actor_id and not reason and any(row["action"] != AuditAction.CREATE for row in rows):
        # The database refuses this too (CHECK user_change_has_reason); this message says why.
        raise MissingAuditReason("A user's change must have a reason: call set_audit_reason() first.")
    session.connection().execute(insert(AuditEvent.__table__), rows)



@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def forget_reason(session: Session) -> None:
    """A reason explains one transaction. Clear it when that transaction ends, so a
    long-lived session (a job, a script) can't stamp it on a later, unrelated change.
    The actor stays: it's still the same person (or the system) using the session."""
    session.info.pop(REASON_KEY, None)