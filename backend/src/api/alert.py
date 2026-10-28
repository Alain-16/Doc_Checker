import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.review.policies import PolicyError, current_policies, save_policy_version
from src.review.raising import refresh_alerts
from src.config.database import get_session
from src.models import Alert, AlertPolicy
from src.models.alert import AlertEvent, AlertStatus, DeliveryChannel, DeliveryKind, DeliveryStatus
from src.models.compliance import FindingSeverity
from src.models.user import UserRole


router = APIRouter(tags=["alerts"])
LIVE_STATUSES = [AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED]
MAX_PAGE_SIZE = 500


# --- Response and request shapes ---


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: DeliveryKind
    channel: DeliveryChannel
    audience_role: UserRole
    recipient_id: uuid.UUID | None
    status: DeliveryStatus
    created_at: datetime
    sent_at: datetime | None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: AlertEvent
    severity: FindingSeverity
    status: AlertStatus
    title: str
    message: str
    audience_role: UserRole
    document_id: uuid.UUID | None
    component_id: uuid.UUID | None
    vendor_file_id: uuid.UUID | None
    finding_id: uuid.UUID | None
    created_at: datetime
    reminder_count: int
    escalated_at: datetime | None
    acknowledged_at: datetime | None
    acknowledgement_note: str | None
    resolved_at: datetime | None
    resolution: str | None


class AlertDetailOut(AlertOut):
    evidence: dict[str, Any]
    deliveries: list[DeliveryOut]


class AlertSummaryOut(BaseModel):
    """Counts for the dashboard badge: live alerts only."""

    open: int
    acknowledged: int
    escalated: int
    by_severity: dict[FindingSeverity, int]


class Acknowledgement(BaseModel):
    note: str | None = Field(default=None, description="Optional: what you are doing about it.")


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event: AlertEvent
    version: int
    enabled: bool
    audience_role: UserRole
    reminder_days: int
    escalate_critical_after_days: int
    escalate_after_days: int
    parameters: dict[str, Any]
    change_reason: str
    created_at: datetime


class PolicySettings(BaseModel):
    """A complete new version: every setting is sent, so each version stands on its own."""

    enabled: bool
    audience_role: UserRole
    reminder_days: int = Field(gt=0)
    escalate_critical_after_days: int = Field(gt=0)
    escalate_after_days: int = Field(gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    change_reason: str = Field(min_length=10, description="Why the policy changes (audit trail).")



@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    status_in: list[AlertStatus] = Query(default=LIVE_STATUSES, alias="status"),
    event: AlertEvent | None = None,
    severity: FindingSeverity | None = None,
    limit: int = Query(default=100, gt=0, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_session),
) -> list[Alert]:

    query = select(Alert).where(Alert.status.in_(status_in))
    if event:
        query = query.where(Alert.event == event)
    if severity:
        query = query.where(Alert.severity == severity)

    return list(session.scalars(query.order_by(Alert.created_at.desc()).limit(limit)))


@router.get("/alerts/summary", response_model=AlertSummaryOut)
def alert_summary(session: Session = Depends(get_session)) -> AlertSummaryOut:
    live = Alert.status.in_(LIVE_STATUSES)
    by_status = dict(session.execute(select(Alert.status, func.count()).where(live).group_by(Alert.status)).all())
    by_severity = dict(session.execute(select(Alert.severity, func.count()).where(live).group_by(Alert.severity)).all())
    escalated = session.scalar(select(func.count()).where(live, Alert.escalated_at.is_not(None)))
    return AlertSummaryOut(
        open=by_status.get(AlertStatus.OPEN, 0),
        acknowledged=by_status.get(AlertStatus.ACKNOWLEDGED, 0),
        escalated=escalated,
        by_severity={severity: by_severity.get(severity, 0) for severity in FindingSeverity},
    )    

def get_alert(session: Session, alert_id: uuid.UUID) -> Alert:
    alert = session.scalar(select(Alert).where(Alert.id == alert_id).options(selectinload(Alert.deliveries)))
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found.")
    return alert


@router.get("/alerts/{alert_id}", response_model=AlertDetailOut)
def read_alert(alert_id: uuid.UUID, session: Session = Depends(get_session)) -> Alert:
    return get_alert(session, alert_id)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertDetailOut)
def acknowledge_alert(alert_id: uuid.UUID, body: Acknowledgement, session: Session = Depends(get_session)) -> Alert:
    """"I've seen it and I'm on it." Stops reminders and escalation; doesn't close the alert."""
    alert = get_alert(session, alert_id)
    if alert.status != AlertStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only open alerts can be acknowledged; this one is {alert.status}.")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.now(UTC)
    alert.acknowledgement_note = body.note
    session.commit()
    return alert


@router.get("/alert-policies", response_model=list[PolicyOut])
def list_policies(session: Session = Depends(get_session)) -> list[AlertPolicy]:
    """The current version of each event's policy."""
    return sorted(current_policies(session).values(), key=lambda policy: policy.event)


@router.get("/alert-policies/{event}", response_model=list[PolicyOut])
def policy_history(event: AlertEvent, session: Session = Depends(get_session)) -> list[AlertPolicy]:
    """Every version of one event's policy, oldest first."""
    return list(session.scalars(select(AlertPolicy).where(AlertPolicy.event == event).order_by(AlertPolicy.version)))


@router.put("/alert-policies/{event}", response_model=PolicyOut)
def change_policy(event: AlertEvent, body: PolicySettings, session: Session = Depends(get_session)) -> AlertPolicy:
    """Save new settings as the next version, then bring live alerts in line with them."""
    try:
        policy = save_policy_version(session, event, **body.model_dump())
    except PolicyError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    # Cheap (a few queries), so done right away: turning an event off resolves its alerts now.
    refresh_alerts(session, datetime.now(UTC))
    session.commit()
    return policy