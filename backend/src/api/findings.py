import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from src.api.documents import DocumentOut, FindingBrief, documents_by_id, finding_brief
from src.auth.dependencies import current_user
from src.config.database import get_session
from src.models import ComplianceFinding, ComplianceRuleVersion, Component, Document, Vendor
from src.models.compliance import FindingSeverity

# Read-only: findings are opened and resolved by the rules engine, never by a click.
# A finding resolves itself when a later evaluation no longer produces it (the
# document is replaced, a reviewer corrects the value, or the rule changes).
router = APIRouter(prefix="/findings", tags=["findings"], dependencies=[Depends(current_user)])
MAX_PAGE_SIZE = 2000


class FindingOut(FindingBrief):
    # What the finding is about: one document, or a component or vendor as a whole.
    subject: Literal["document", "component", "vendor"]
    document_id: uuid.UUID | None
    document: DocumentOut | None
    vendor_id: uuid.UUID | None
    vendor_name: str | None
    component_id: uuid.UUID | None
    component_name: str | None
    previous_status: str | None
    last_evaluated_at: str


def findings_query() -> Select:
    # A component- or vendor-level finding names its subject directly; a document
    # finding reaches its vendor and component through the document.
    doc = aliased(Document)
    vendor = aliased(Vendor)
    component = aliased(Component)
    return (
        select(ComplianceFinding, ComplianceRuleVersion, vendor.id, vendor.name, component.id, component.name)
        .join(ComplianceRuleVersion, ComplianceFinding.rule_version_id == ComplianceRuleVersion.id)
        .outerjoin(doc, ComplianceFinding.document_id == doc.id)
        .outerjoin(
            component,
            (component.id == ComplianceFinding.component_id) | (component.id == doc.component_id),
        )
        .outerjoin(
            vendor,
            (vendor.id == ComplianceFinding.vendor_id) | (vendor.id == doc.vendor_id) | (vendor.id == component.vendor_id),
        )
    )


def finding_rows_out(session: Session, rows: list) -> list[FindingOut]:
    documents = documents_by_id(session, list({f.document_id for f, *_ in rows if f.document_id}))
    out = []
    for finding, version, vendor_id, vendor_name, component_id, component_name in rows:
        subject = "document" if finding.document_id else "component" if finding.component_id else "vendor"
        out.append(
            FindingOut(
                **finding_brief(finding, version).model_dump(),
                subject=subject,
                document_id=finding.document_id,
                document=documents.get(finding.document_id) if finding.document_id else None,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                component_id=component_id,
                component_name=component_name,
                previous_status=finding.previous_status,
                last_evaluated_at=finding.last_evaluated_at.isoformat(),
            )
        )
    return out


@router.get("", response_model=list[FindingOut])
def list_findings(
    state: Literal["open", "resolved", "all"] = Query(default="open", alias="status"),
    severity: FindingSeverity | None = None,
    vendor_id: uuid.UUID | None = None,
    component_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    rule_code: str | None = None,
    limit: int = Query(default=500, gt=0, le=MAX_PAGE_SIZE),
    session: Session = Depends(get_session),
) -> list[FindingOut]:
    query = findings_query()
    if state != "all":
        query = query.where(ComplianceFinding.resolved.is_(state == "resolved"))
    if severity:
        query = query.where(ComplianceFinding.severity == severity)
    if document_id:
        query = query.where(ComplianceFinding.document_id == document_id)
    if rule_code:
        query = query.where(ComplianceFinding.rule_code == rule_code)
    rows = session.execute(query.order_by(ComplianceFinding.created_at.desc()).limit(limit)).all()
    # Vendor and component filters apply to the resolved subject (direct or via the document).
    if vendor_id:
        rows = [r for r in rows if r[2] == vendor_id]
    if component_id:
        rows = [r for r in rows if r[4] == component_id]
    severity_order = {FindingSeverity.CRITICAL: 0, FindingSeverity.WARNING: 1, FindingSeverity.INFO: 2}
    rows.sort(key=lambda r: (r[0].resolved, severity_order.get(r[0].severity, 3)))
    return finding_rows_out(session, rows)


@router.get("/{finding_id}", response_model=FindingOut)
def read_finding(finding_id: uuid.UUID, session: Session = Depends(get_session)) -> FindingOut:
    rows = session.execute(findings_query().where(ComplianceFinding.id == finding_id)).all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found.")
    return finding_rows_out(session, rows[:1])[0]
