import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.documents import DocumentOut, documents_query, document_out
from src.auth.dependencies import current_user
from src.config.database import get_session
from src.models import (
    ComplianceFinding,
    ComplianceRuleVersion,
    Component,
    Document,
    ReviewItem,
    User,
    Vendor,
    VendorFile,
)
from src.models.document import ComplianceStatus
from src.models.review import ReviewStatus
from src.models.vendor_file import ProcessingStatus

# Counts for the dashboard and the vendor tables. Only current documents (not
# superseded) of fully processed files count: that is "what is on file today".
router = APIRouter(tags=["statistics"], dependencies=[Depends(current_user)])


class StatusCounts(BaseModel):
    documents: int = 0
    current: int = 0
    approaching: int = 0
    stale: int = 0
    needs_review: int = 0
    superseded: int = 0
    open_findings: int = 0


class VendorStatsOut(StatusCounts):
    vendor_id: uuid.UUID
    components: int
    last_upload: datetime | None


class ComponentStatsOut(StatusCounts):
    component_id: uuid.UUID
    vendor_id: uuid.UUID


class ActivityOut(BaseModel):
    kind: str  # upload, finding, finding_resolved, review, rule
    text: str
    who: str  # a person's name, or "System"
    at: datetime
    link: str | None  # a frontend path


class DashboardOut(BaseModel):
    totals: StatusCounts
    findings_by_severity: dict[str, int]
    vendors: int
    open_reviews: int
    files_processing: int
    files_failed: int
    last_evaluated_at: datetime | None
    upcoming: list[DocumentOut]  # approaching review, earliest governing date first
    activity: list[ActivityOut]


STATUS_FIELD = {
    ComplianceStatus.CURRENT: "current",
    ComplianceStatus.APPROACHING_REVIEW: "approaching",
    ComplianceStatus.STALE: "stale",
    ComplianceStatus.NEEDS_REVIEW: "needs_review",
}


def processed() -> object:
    return VendorFile.processing_status == ProcessingStatus.COMPLETED


def counts_by(session: Session, column) -> dict[uuid.UUID | None, StatusCounts]:
    """Document status counts grouped by vendor_id or component_id, plus open findings."""
    out: dict[uuid.UUID | None, StatusCounts] = defaultdict(StatusCounts)
    rows = session.execute(
        select(column, Document.compliance_status, Document.superseded_by_id.is_(None), func.count())
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .where(processed())
        .group_by(column, Document.compliance_status, Document.superseded_by_id.is_(None))
    ).all()
    for key, compliance_status, is_current, n in rows:
        c = out[key]
        if not is_current:
            c.superseded += n
            continue
        c.documents += n
        setattr(c, STATUS_FIELD[compliance_status], getattr(c, STATUS_FIELD[compliance_status]) + n)
    for key, n in open_findings_by(session, column).items():
        out[key].open_findings += n
    return out


def open_findings_by(session: Session, column) -> dict[uuid.UUID | None, int]:
    """Open findings per vendor or component: about a document of it, or about it directly."""
    via_document = session.execute(
        select(column, func.count())
        .select_from(ComplianceFinding)
        .join(Document, ComplianceFinding.document_id == Document.id)
        .where(ComplianceFinding.resolved.is_(False))
        .group_by(column)
    ).all()
    out: dict[uuid.UUID | None, int] = defaultdict(int)
    for key, n in via_document:
        out[key] += n
    if column is Document.vendor_id:
        direct = session.execute(
            select(ComplianceFinding.vendor_id, func.count())
            .where(ComplianceFinding.resolved.is_(False), ComplianceFinding.vendor_id.is_not(None))
            .group_by(ComplianceFinding.vendor_id)
        ).all()
        via_component = session.execute(
            select(Component.vendor_id, func.count())
            .join(ComplianceFinding, ComplianceFinding.component_id == Component.id)
            .where(ComplianceFinding.resolved.is_(False))
            .group_by(Component.vendor_id)
        ).all()
        for key, n in [*direct, *via_component]:
            out[key] += n
    else:
        direct = session.execute(
            select(ComplianceFinding.component_id, func.count())
            .where(ComplianceFinding.resolved.is_(False), ComplianceFinding.component_id.is_not(None))
            .group_by(ComplianceFinding.component_id)
        ).all()
        for key, n in direct:
            out[key] += n
    return out


@router.get("/vendors/stats", response_model=list[VendorStatsOut])
def vendor_stats(session: Session = Depends(get_session)) -> list[VendorStatsOut]:
    counts = counts_by(session, Document.vendor_id)
    components = dict(session.execute(select(Component.vendor_id, func.count()).group_by(Component.vendor_id)).all())
    last_upload = dict(
        session.execute(
            select(Document.vendor_id, func.max(VendorFile.created_at))
            .join(VendorFile, Document.vendor_file_id == VendorFile.id)
            .group_by(Document.vendor_id)
        ).all()
    )
    return [
        VendorStatsOut(vendor_id=v, components=components.get(v, 0), last_upload=last_upload.get(v), **counts[v].model_dump())
        for v in session.scalars(select(Vendor.id))
    ]


@router.get("/components/stats", response_model=list[ComponentStatsOut])
def component_stats(vendor_id: uuid.UUID | None = None, session: Session = Depends(get_session)) -> list[ComponentStatsOut]:
    counts = counts_by(session, Document.component_id)
    query = select(Component.id, Component.vendor_id)
    if vendor_id:
        query = query.where(Component.vendor_id == vendor_id)
    return [ComponentStatsOut(component_id=c, vendor_id=v, **counts[c].model_dump()) for c, v in session.execute(query).all()]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(session: Session = Depends(get_session)) -> DashboardOut:
    totals = StatusCounts()
    for c in counts_by(session, Document.vendor_id).values():
        for field in StatusCounts.model_fields:
            if field != "open_findings":
                setattr(totals, field, getattr(totals, field) + getattr(c, field))
    severity = dict(
        session.execute(
            select(ComplianceFinding.severity, func.count()).where(ComplianceFinding.resolved.is_(False)).group_by(ComplianceFinding.severity)
        ).all()
    )
    totals.open_findings = sum(severity.values())
    files = dict(session.execute(select(VendorFile.processing_status, func.count()).group_by(VendorFile.processing_status)).all())

    upcoming_rows = session.execute(
        documents_query()
        .where(
            processed(),
            Document.superseded_by_id.is_(None),
            Document.compliance_status == ComplianceStatus.APPROACHING_REVIEW,
        )
        .order_by(Document.governing_date.asc().nulls_last())
        .limit(6)
    ).all()

    return DashboardOut(
        totals=totals,
        findings_by_severity={str(k): v for k, v in severity.items()},
        vendors=session.scalar(select(func.count()).select_from(Vendor)) or 0,
        open_reviews=session.scalar(select(func.count()).where(ReviewItem.status == ReviewStatus.OPEN)) or 0,
        files_processing=files.get(ProcessingStatus.QUEUED, 0) + files.get(ProcessingStatus.RUNNING, 0),
        files_failed=files.get(ProcessingStatus.FAILED, 0),
        last_evaluated_at=session.scalar(select(func.max(Document.status_evaluated_at))),
        upcoming=[document_out(r) for r in upcoming_rows],
        activity=recent_activity(session),
    )


def recent_activity(session: Session, limit: int = 8) -> list[ActivityOut]:
    """The latest events across uploads, findings, review decisions and rule changes."""
    events: list[ActivityOut] = []
    for f in session.scalars(select(VendorFile).order_by(VendorFile.created_at.desc()).limit(limit)):
        events.append(ActivityOut(kind="upload", text=f"Vendor file uploaded — {f.filename} ({f.page_count} pages)", who="System", at=f.created_at, link=f"/vendor-files/{f.id}"))
    for finding, name in session.execute(
        select(ComplianceFinding, ComplianceRuleVersion.name)
        .join(ComplianceRuleVersion, ComplianceFinding.rule_version_id == ComplianceRuleVersion.id)
        .order_by(ComplianceFinding.created_at.desc())
        .limit(limit)
    ).all():
        events.append(ActivityOut(kind="finding", text=f"Finding raised — {name}: {finding.message}", who="System", at=finding.created_at, link=f"/findings?open={finding.id}"))
    for finding, name in session.execute(
        select(ComplianceFinding, ComplianceRuleVersion.name)
        .join(ComplianceRuleVersion, ComplianceFinding.rule_version_id == ComplianceRuleVersion.id)
        .where(ComplianceFinding.resolved.is_(True))
        .order_by(ComplianceFinding.resolved_at.desc())
        .limit(limit)
    ).all():
        events.append(ActivityOut(kind="finding_resolved", text=f"Finding resolved — {name}", who="System", at=finding.resolved_at, link=f"/findings?open={finding.id}"))
    for item, who in session.execute(
        select(ReviewItem, User.full_name)
        .join(User, ReviewItem.resolved_by_id == User.id)
        .where(ReviewItem.status == ReviewStatus.RESOLVED)
        .order_by(ReviewItem.resolved_at.desc())
        .limit(limit)
    ).all():
        events.append(ActivityOut(kind="review", text=f"Review decision — {item.resolution.value.replace('_', ' ')}: {item.reason}", who=who, at=item.resolved_at, link=f"/review?item={item.id}"))
    for version, who in session.execute(
        select(ComplianceRuleVersion, User.full_name)
        .outerjoin(User, ComplianceRuleVersion.changed_by_id == User.id)
        .order_by(ComplianceRuleVersion.created_at.desc())
        .limit(limit)
    ).all():
        events.append(ActivityOut(kind="rule", text=f"Rule signed — {version.name} v{version.version}", who=who or "System", at=version.created_at, link=f"/rules/{version.rule_id}"))
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]
