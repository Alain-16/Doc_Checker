from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.review.policies import (
    ComingDueParameters,
    FindingAlertParameters,
    ReviewOverdueParameters,
    current_policies,
    parameters_of,
)
from src.models import Alert, AlertDelivery, AlertPolicy, ComplianceFinding, Component, Document, ReviewItem, VendorFile
from src.models.alert import AlertEvent, AlertStatus, DeliveryChannel, DeliveryKind
from src.models.compliance import FindingSeverity
from src.models.document import ComplianceStatus
from src.models.review import ReviewStatus

STATUS_SEVERITY = {
    ComplianceStatus.CURRENT: 0,
    ComplianceStatus.APPROACHING_REVIEW: 1,
    ComplianceStatus.STALE: 2,
    ComplianceStatus.NEEDS_REVIEW: 3,
}
# Why an alert closed, per event, when its cause is no longer there.
RESOLUTIONS = {
    AlertEvent.FINDING: "The finding was resolved or no longer needs an alert.",
    AlertEvent.COMING_DUE: "The review is no longer coming due (new document, new date, or now stale).",
    AlertEvent.REVIEW_OVERDUE: "The overdue review items were resolved.",
}
POLICY_DISABLED = "Alerts for this event were turned off in the alert policy."


@dataclass
class AlertDraft:
    """An alert that should be open, before it is saved."""

    title: str
    message: str
    severity: FindingSeverity
    evidence: dict[str, Any] = field(default_factory=dict)
    document_id: Any = None
    component_id: Any = None
    vendor_file_id: Any = None
    finding_id: Any = None



def describe_document(document: Document) -> str:
    """'Compliance Bulletin (pages 6-12)': how a person recognises the document."""
    kind = document.document_type.display_name if document.document_type else "Unclassified document"
    return f"{kind} (pages {document.start_page}-{document.end_page})"


def got_worse(finding: ComplianceFinding) -> bool:
    """New, or worse than the finding it replaced. Better ("stale -> approaching") is not alerted."""
    return finding.previous_status is None or STATUS_SEVERITY[finding.status] > STATUS_SEVERITY[finding.previous_status]


def finding_drafts(session: Session, parameters: FindingAlertParameters) -> dict[str, AlertDraft]:
    findings = session.scalars(
        select(ComplianceFinding)
        .where(ComplianceFinding.resolved.is_(False))
        .options(
            selectinload(ComplianceFinding.document).selectinload(Document.document_type),
            selectinload(ComplianceFinding.rule_version),
        )
    ).all()
    component_names = dict(session.execute(select(Component.id, Component.name)).all())
    drafts = {}
    for finding in findings:
        critical = finding.severity == FindingSeverity.CRITICAL and parameters.always_alert_critical
        if not critical and not (finding.status in parameters.statuses and got_worse(finding)):
            continue
        if finding.document:
            subject = describe_document(finding.document)
        else:
            subject = f"Component {component_names.get(finding.component_id, '')}".strip()
        status = finding.status.value.replace("_", " ")
        drafts[f"finding:{finding.id}"] = AlertDraft(
            # The rule's name tells two alerts on the same document apart.
            title=f"{subject}: {status} ({finding.rule_version.name})",
            message=finding.message,
            severity=finding.severity,
            evidence={"rule_code": finding.rule_code, "status": finding.status.value, **finding.evidence},
            document_id=finding.document_id,
            component_id=finding.component_id,
            vendor_file_id=finding.document.vendor_file_id if finding.document else None,
            finding_id=finding.id,
        )
    return drafts

def sync_alerts(
    session: Session, event: AlertEvent, policy: AlertPolicy | None, drafts: dict[str, AlertDraft], now: datetime
) -> None:
    live = {
        alert.dedup_key: alert
        for alert in session.scalars(select(Alert).where(Alert.event == event, Alert.status != AlertStatus.RESOLVED))
    }
    enabled = policy is not None and policy.enabled
    if not enabled:
        drafts = {}

    # Cause gone (or alerts turned off): resolve. Nobody resolves an alert by hand.
    for key, alert in live.items():
        if key not in drafts:
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = now
            alert.resolution = RESOLUTIONS[event] if enabled else POLICY_DISABLED

    for key, draft in drafts.items():
        alert = live.get(key)
        if alert is not None:
            # Same cause, still there: keep its text current, but don't notify again.
            alert.title, alert.message, alert.severity, alert.evidence = (
                draft.title, draft.message, draft.severity, draft.evidence,
            )
            continue
        alert = Alert(
            event=event,
            dedup_key=key,
            severity=draft.severity,
            title=draft.title,
            message=draft.message,
            evidence=draft.evidence,
            audience_role=policy.audience_role,
            policy_id=policy.id,
            document_id=draft.document_id,
            component_id=draft.component_id,
            vendor_file_id=draft.vendor_file_id,
            finding_id=draft.finding_id,
            last_notified_at=now,
        )
        # The first notification. It waits as "pending" until there are users (Phase B).
        alert.deliveries.append(
            AlertDelivery(kind=DeliveryKind.INITIAL, channel=DeliveryChannel.IN_APP, audience_role=policy.audience_role)
        )
        session.add(alert)


def refresh_alerts(session: Session, now: datetime) -> None:
    """Bring every event's alerts in line with the current findings and review queue."""
    policies = current_policies(session)

    def drafts_for(event: AlertEvent) -> dict[str, AlertDraft]:
        policy = policies.get(event)
        if policy is None or not policy.enabled:
            return {}
        parameters = parameters_of(policy)
        if event == AlertEvent.FINDING:
            return finding_drafts(session, parameters)
        if event == AlertEvent.COMING_DUE:
            return coming_due_drafts(session, parameters, now.date())
        return review_overdue_drafts(session, parameters, now)

    for event in AlertEvent:
        sync_alerts(session, event, policies.get(event), drafts_for(event), now)


def coming_due_drafts(session: Session, parameters: ComingDueParameters, today: date) -> dict[str, AlertDraft]:
    """Documents whose review falls due within the window and isn't overdue yet.

    The due date comes from the age rule's own finding (evidence["review_due"]),
    so this never recomputes ages in a second, possibly different, way.
    """
    findings = session.scalars(
        select(ComplianceFinding)
        .where(
            ComplianceFinding.resolved.is_(False),
            ComplianceFinding.document_id.is_not(None),
            ComplianceFinding.evidence.has_key("review_due"),
        )
        .options(selectinload(ComplianceFinding.document).selectinload(Document.document_type))
    ).all()
    drafts = {}
    for finding in findings:
        due = date.fromisoformat(finding.evidence["review_due"])
        days_left = (due - today).days
        if not 0 <= days_left <= parameters.window_days:
            continue  # overdue already (the stale finding alerts) or still far away
        subject = describe_document(finding.document)
        drafts[f"coming_due:{finding.document_id}:{due.isoformat()}"] = AlertDraft(
            title=f"{subject}: review due in {days_left} day(s)",
            message=f"Review falls due on {due:%d-%b-%Y}. {finding.message}",
            severity=finding.severity,
            evidence={"review_due": due.isoformat(), "days_left": days_left, "rule_code": finding.rule_code},
            document_id=finding.document_id,
            vendor_file_id=finding.document.vendor_file_id,
            finding_id=finding.id,
        )
    return drafts


def review_overdue_drafts(session: Session, parameters: ReviewOverdueParameters, now: datetime) -> dict[str, AlertDraft]:
    """One alert per file whose review items have waited too long."""
    cutoff = now - timedelta(days=parameters.older_than_days)
    rows = session.execute(
        select(VendorFile.id, VendorFile.filename, func.count(ReviewItem.id), func.min(ReviewItem.created_at))
        .join(ReviewItem, ReviewItem.vendor_file_id == VendorFile.id)
        .where(ReviewItem.status == ReviewStatus.OPEN, ReviewItem.created_at < cutoff)
        .group_by(VendorFile.id, VendorFile.filename)
    ).all()
    return {
        f"review_overdue:{file_id}": AlertDraft(
            title=f"{count} review item(s) waiting more than {parameters.older_than_days} days",
            message=(
                f"{filename}: {count} uncertain result(s) have waited since {oldest:%d-%b-%Y}. "
                "Until they are reviewed, the documents they belong to stay at 'needs review'."
            ),
            severity=FindingSeverity.WARNING,
            evidence={"open_items": count, "oldest": oldest.isoformat()},
            vendor_file_id=file_id,
        )
        for file_id, filename, count, oldest in rows
    }
