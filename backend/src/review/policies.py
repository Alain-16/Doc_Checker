from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.auth.signatures import sign
from src.models import AlertPolicy, User
from src.models.audit import SignatureMeaning
from src.models.alert import AlertEvent
from src.models.document import ComplianceStatus
from src.models.user import UserRole


class EventParameters(BaseModel):

    model_config = ConfigDict(extra="forbid")

class FindingAlertParameters(EventParameters):

    statuses: list[ComplianceStatus] = Field(
        default=[ComplianceStatus.APPROACHING_REVIEW, ComplianceStatus.STALE, ComplianceStatus.NEEDS_REVIEW],
        description="Finding statuses that raise an alert when a finding opens or gets worse."
    )
    always_alert_critical: bool = Field(
        default= True,
        description="Alert on every critical finding, whatever its status."
    )

class ComingDueParameters(EventParameters):
    window_days: int = Field(default=90, gt=0, description="Alert when a review falls due within this many days")

class ReviewOverdueParameters(EventParameters):
    older_than_days: int = Field(default=5, dt=0, description="Alert when review items stay open longer than this.")

EVENT_PARAMETERS: dict[AlertEvent, type[EventParameters]] ={
    AlertEvent.FINDING: FindingAlertParameters,
    AlertEvent.COMING_DUE: ComingDueParameters,
    AlertEvent.REVIEW_OVERDUE: ReviewOverdueParameters,    
} 

class PolicyError(ValueError):
    """A policy that can't be saved; the message says why, for the person editing it."""

def current_policies(session: Session) -> dict[AlertEvent, AlertPolicy]:
    latest = (
        select(AlertPolicy.event, func.max(AlertPolicy.version).label("version"))
        .group_by(AlertPolicy.event)
        .subquery()
    )

    policies = session.scalars(
        select(AlertPolicy).join(
            latest, (AlertPolicy.event == latest.c.event) & (AlertPolicy.version == latest.c.version)
        )

    )
    return {policy.event: policy for policy in policies}

def parameters_of(policy: AlertPolicy) ->  Any:
    return EVENT_PARAMETERS[policy.event].model_validate(policy.parameters)


def save_policy_version(
        session: Session,
        event: AlertEvent,
        *,
        signer: User,
        enabled: bool,
        audience_role: UserRole,
        reminder_days: int,
        escalate_critical_after_days: int,
        escalate_after_days: int,
        parameters: dict[str, Any],
        change_reason: str,        
) -> AlertPolicy:
    try:
        checked = EVENT_PARAMETERS[event].model_validate(parameters)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'parameters'}: {e['msg']}" for e in error.errors())
        raise PolicyError(f"Invalid parameters for {event}: {problems}") from error
    if min(reminder_days, escalate_critical_after_days, escalate_after_days) <= 0:
        raise PolicyError("Reminder and escalation days must be at least 1.")

    current = current_policies(session).get(event)
    policy = AlertPolicy(
        event=event,
        version=current.version + 1 if current else 1,
        enabled=enabled,
        audience_role=audience_role,
        reminder_days=reminder_days,
        escalate_critical_after_days=escalate_critical_after_days,
        escalate_after_days=escalate_after_days,
        # Stored with defaults filled in, so a later change of a default in code
        # never silently changes what this version meant.
        parameters=checked.model_dump(mode="json"),
        change_reason=change_reason,
        changed_by_id=signer.id,
    )
    sign(session, signer, SignatureMeaning.APPROVAL, policy, change_reason)
    session.add(policy)
    session.flush()
    return policy