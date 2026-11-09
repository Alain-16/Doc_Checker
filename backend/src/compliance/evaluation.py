"""Run the active compliance rules and record what they find (Feature 7).

Called by the pipeline (one file), by the nightly job (everything: documents
go stale as time passes), and after any rule change.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session, selectinload

from src.review.raising import refresh_alerts

from src.compliance.facts import (
    AttributeFact,
    DateFact,
    DocumentFacts,
    GroupDocument,
    GroupFacts,
    Outcome,
    ReviewFact,
    RuleParameters,
)
from src.compliance.rule_kinds import RULE_KINDS, RuleKindSpec
from src.models import (
    ComplianceFinding,
    ComplianceRule,
    ComplianceRuleVersion,
    Component,
    Document,
    DocumentAttribute,
    DocumentDate,
    DocumentType,
    ReviewItem,
    Vendor,
    VendorFile,
)
from src.models.compliance import RuleKind, RuleLevel
from src.models.document import ComplianceStatus
from src.models.review import ReviewStatus
from src.models.vendor_file import ProcessingStatus

# Shown on a document a newer version replaced (it is no longer judged).
SUPERSEDED_REASON = "Replaced by a newer version of this document; no longer evaluated."
# The worst finding decides a document's status.
STATUS_SEVERITY = {
    ComplianceStatus.CURRENT: 0,
    ComplianceStatus.APPROACHING_REVIEW: 1,
    ComplianceStatus.STALE: 2,
    ComplianceStatus.NEEDS_REVIEW: 3,
}


@dataclass
class ActiveRule:
    rule: ComplianceRule
    version: ComplianceRuleVersion
    spec: RuleKindSpec
    parameters: RuleParameters


def active_rules(session: Session) -> list[ActiveRule]:
    """Every rule whose latest version is active, with its parameters parsed."""
    rules = session.scalars(select(ComplianceRule).options(selectinload(ComplianceRule.versions))).all()
    return [
        ActiveRule(rule, rule.current, RULE_KINDS[rule.kind], RULE_KINDS[rule.kind].parameters.model_validate(rule.current.parameters))
        for rule in rules
        if rule.current.active
    ]


def rules_for_document(rules: list[ActiveRule], document: Document) -> list[ActiveRule]:
    """Document-level rules for every type plus this document's type.

    For age, a type's own rules replace the default one: a bulletin is judged
    by its signature date, not by the generic "latest own date" rule.
    """
    applicable = [
        r for r in rules
        if r.rule.level == RuleLevel.DOCUMENT and r.rule.document_type_id in (None, document.document_type_id)
    ]
    has_typed_age = any(r.rule.kind == RuleKind.DOCUMENT_AGE and r.rule.document_type_id for r in applicable)
    if has_typed_age:
        applicable = [r for r in applicable if not (r.rule.kind == RuleKind.DOCUMENT_AGE and r.rule.document_type_id is None)]
    return applicable


# =============================================================================
# Gathering facts
# =============================================================================


def document_facts(session: Session, document: Document) -> DocumentFacts:
    dates = session.scalars(select(DocumentDate).where(DocumentDate.document_id == document.id)).all()
    attributes = session.scalars(
        select(DocumentAttribute)
        .where(DocumentAttribute.document_id == document.id)
        .options(selectinload(DocumentAttribute.key_attribute))
    ).all()
    # Page-level items (e.g. OCR) were raised before the file was split into
    # documents, so they have no document_id: they're matched by page range.
    reviews = session.scalars(
        select(ReviewItem).where(
            ReviewItem.status == ReviewStatus.OPEN,
            or_(
                ReviewItem.document_id == document.id,
                and_(
                    ReviewItem.document_id.is_(None),
                    ReviewItem.vendor_file_id == document.vendor_file_id,
                    ReviewItem.page_number.between(document.start_page, document.end_page),
                ),
            ),
        )
    ).all()
    document_type = document.document_type
    return DocumentFacts(
        document_type=document_type.name if document_type else "unknown",
        document_type_label=document_type.display_name if document_type else "Unknown",
        dates=[
            DateFact(d.date_type, d.date_value, d.page_number, d.original_text, d.is_document_date) for d in dates
        ],
        attributes={
            a.key_attribute.name: AttributeFact(
                a.key_attribute.name, a.key_attribute.display_name, a.value, a.page_number,
                a.key_attribute.required, a.evidence_snippet,
            )
            for a in attributes
        },
        open_reviews=[ReviewFact(r.item_kind, r.reason, r.page_number) for r in reviews],
    )


def group_facts(session: Session, name: str, belongs: ColumnElement[bool]) -> GroupFacts:
    labels = dict(session.execute(select(DocumentType.name, DocumentType.display_name)).all())
    documents = session.scalars(
        select(Document).where(belongs).options(selectinload(Document.document_type))
    ).all()
    current, superseded_types = [], {}
    for document in documents:
        type_name = document.document_type.name if document.document_type else "unknown"
        if document.superseded_by_id is None:
            current.append(
                GroupDocument(
                    type_name, labels.get(type_name, type_name), document.compliance_status, document.title,
                    document_facts(session, document),
                )
            )
        else:
            superseded_types[type_name] = labels.get(type_name, type_name)
    return GroupFacts(name, current, superseded_types, labels)


def component_facts(session: Session, component: Component) -> GroupFacts:
    """Its own documents, plus its vendor's company-level ones."""
    company_level = and_(Document.vendor_id == component.vendor_id, Document.component_id.is_(None))
    return group_facts(session, component.name, or_(Document.component_id == component.id, company_level))


def vendor_facts(session: Session, vendor: Vendor) -> GroupFacts:
    """Every document of the vendor, whichever component it is about."""
    return group_facts(session, vendor.name, Document.vendor_id == vendor.id)


# =============================================================================
# Recording findings, with history
# =============================================================================


def open_findings(session: Session, subject_column, subject_id) -> dict[str, ComplianceFinding]:
    return {
        finding.rule_code: finding
        for finding in session.scalars(
            select(ComplianceFinding).where(subject_column == subject_id, ComplianceFinding.resolved.is_(False))
        )
    }


def record_outcomes(
    session: Session,
    subject: dict,  # {"document_id": ...}, {"component_id": ...} or {"vendor_id": ...}
    results: list[tuple[ActiveRule, Outcome | None]],
    now: datetime,
) -> None:
    """Update the subject's findings so the open ones match this evaluation.

    Same outcome as before: only last_evaluated_at moves. Changed outcome: the
    old finding is resolved and a new one opened, so the history shows when
    and why it changed. Nothing to say any more (fixed, or rule deactivated):
    the old finding is resolved.
    """
    (column_name, subject_id), = subject.items()
    existing = open_findings(session, getattr(ComplianceFinding, column_name), subject_id)
    produced = {active.rule.code for active, outcome in results if outcome is not None}

    for code, finding in existing.items():
        if code not in produced:
            finding.resolved, finding.resolved_at = True, now

    for active, outcome in results:
        if outcome is None:
            continue
        finding = existing.get(active.rule.code)
        if finding and (finding.status, finding.message, finding.rule_version_id) == (
            outcome.status, outcome.message, active.version.id
        ):
            finding.last_evaluated_at = now
            continue
        if finding:
            finding.resolved, finding.resolved_at = True, now
            session.flush()  # resolve first: only one finding per rule may be open (partial unique index)
        session.add(
            ComplianceFinding(
                **subject,
                rule_code=active.rule.code,
                rule_version_id=active.version.id,
                status=outcome.status,
                previous_status = finding.status if finding else None,
                severity=active.version.severity,
                message=outcome.message,
                evidence=outcome.evidence,
                governing_date=outcome.governing_date,
                last_evaluated_at=now,
            )
        )


# =============================================================================
# Evaluating
# =============================================================================


def evaluate_document(session: Session, document: Document, rules: list[ActiveRule], today: date, now: datetime) -> None:
    if document.superseded_by_id is not None:
        # A newer version replaced this one: its problems are no longer anyone's to
        # fix. Resolving its open findings closes their alerts; the resolved
        # findings stay as history ("this bulletin was stale before it was replaced").
        record_outcomes(session, {"document_id": document.id}, [], now)
        document.status_reason = SUPERSEDED_REASON
        document.status_evaluated_at = now
        return

    facts = document_facts(session, document)
    results = [(active, active.spec.check(facts, active.parameters, today)) for active in rules_for_document(rules, document)]
    record_outcomes(session, {"document_id": document.id}, results, now)

    outcomes = [outcome for _, outcome in results if outcome is not None]
    if outcomes:
        worst = max(STATUS_SEVERITY[o.status] for o in outcomes)
        worst_outcomes = [o for o in outcomes if STATUS_SEVERITY[o.status] == worst]
        status, reason = worst_outcomes[0].status, " ".join(o.message for o in worst_outcomes)
    else:
        # Only possible if QA deactivated every age rule: nothing judged it.
        status, reason = ComplianceStatus.NEEDS_REVIEW, "No active rule judged this document."
    age = next((o for (a, o) in results if a.rule.kind == RuleKind.DOCUMENT_AGE and o is not None), None)

    # Copied onto the document because the dashboard reads them constantly.
    document.compliance_status = status
    document.status_reason = reason
    document.governing_date = age.governing_date if age else None
    document.status_evaluated_at = now


def evaluate_component(session: Session, component: Component, rules: list[ActiveRule], today: date, now: datetime) -> None:
    """Run after the component's documents: "no current bulletin" needs their new statuses."""
    session.flush()
    facts = component_facts(session, component)
    results = [(a, a.spec.check(facts, a.parameters, today)) for a in rules if a.rule.level == RuleLevel.COMPONENT]
    record_outcomes(session, {"component_id": component.id}, results, now)


def evaluate_vendor(session: Session, vendor: Vendor, rules: list[ActiveRule], today: date, now: datetime) -> None:
    """Run after its documents, for the same reason."""
    session.flush()
    facts = vendor_facts(session, vendor)
    results = [(a, a.spec.check(facts, a.parameters, today)) for a in rules if a.rule.level == RuleLevel.VENDOR]
    record_outcomes(session, {"vendor_id": vendor.id}, results, now)


def evaluate(session: Session, documents: list[Document], components: list[Component], vendors: list[Vendor]) -> None:
    rules = active_rules(session)
    now = datetime.now(UTC)
    today = now.date()
    for document in documents:
        evaluate_document(session, document, rules, today, now)
    for component in components:
        evaluate_component(session, component, rules, today, now)
    for vendor in vendors:
        evaluate_vendor(session, vendor, rules, today, now)

    session.flush()
    refresh_alerts(session, now)


def evaluate_compliance(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: judge this file's documents, every other document of the
    vendors they belong to, then those vendors and their components.

    All the vendors' documents, not just this file's: if a document here
    superseded an older one, the older one's findings must resolve now, in the
    same run, not stay open. A company-level document can change the outcome
    for any component of its vendor, so all of them are judged.
    """
    own_documents = session.scalars(select(Document).where(Document.vendor_file_id == vendor_file.id)).all()
    # Documents still waiting for identification have no vendor: only they are judged.
    vendor_ids = {d.vendor_id for d in own_documents if d.vendor_id is not None}

    other_documents = session.scalars(
        select(Document)
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .where(
            Document.vendor_id.in_(vendor_ids),
            VendorFile.id != vendor_file.id,
            # This file is still "running" (this is its last stage); the others
            # must have finished processing.
            VendorFile.processing_status == ProcessingStatus.COMPLETED,
        )
    ).all() if vendor_ids else []
    vendors = session.scalars(select(Vendor).where(Vendor.id.in_(vendor_ids)).order_by(Vendor.id)).all()
    components = session.scalars(
        select(Component).where(Component.vendor_id.in_(vendor_ids)).order_by(Component.id)
    ).all()
    evaluate(session, [*own_documents, *other_documents], list(components), list(vendors))


def evaluate_everything(session: Session) -> int:
    """Re-judge every processed document, component and vendor. Returns how many documents."""
    documents = session.scalars(
        select(Document)
        .join(VendorFile, Document.vendor_file_id == VendorFile.id)
        .where(VendorFile.processing_status == ProcessingStatus.COMPLETED)
    ).all()
    components = session.scalars(select(Component)).all()
    vendors = session.scalars(select(Vendor)).all()
    evaluate(session, list(documents), list(components), list(vendors))
    return len(documents)
