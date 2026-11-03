import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from src.copilot.source import Source, document_contexts
from src.copilot.understanding import Scope
from src.llm.models import LlmTask, structured_llm
from src.models import (
    ComplianceFinding,
    Component,
    Document,
    DocumentAttribute,
    DocumentType,
    KeyAttribute,
    VendorFile,
)
from src.models.document import ComplianceStatus
from src.retrieval.search import SearchFilters, hybrid_search

MAX_RECORDS = 25  # rows given to the answer; counts are exact whatever this is
CROSS_DOCUMENT_LIMIT = 8  # documents read one by one on the cross-document route
PASSAGES_PER_DOCUMENT = 2


# =============================================================================
# The tools GPT can choose from
# =============================================================================


class DocumentsTool(BaseModel):
    """List or count documents by type, compliance status and governing date."""

    tool: Literal["documents"]
    action: Literal["list", "count"]
    statuses: list[ComplianceStatus] = Field(description="Empty = any status.")
    governing_before: date | None = Field(description="Only documents whose governing date is before this day.")
    governing_after: date | None
    include_superseded: bool = Field(description="True only if the question is about history or old versions.")


class KeyAttributeTool(BaseModel):
    """The recorded value of one key attribute (e.g. lots, revision) across documents."""

    tool: Literal["key_attribute"]
    attribute: str = Field(description="One of the key attribute names listed.")
    only_not_stated: bool = Field(description="True to list documents that do NOT state it.")


class FindingsTool(BaseModel):
    """Open compliance findings: what the checks flagged and why."""

    tool: Literal["findings"]
    statuses: list[ComplianceStatus] = Field(description="Empty = any.")


class ToolChoice(BaseModel):
    # A plain union (no discriminator): OpenAI's strict JSON schema accepts anyOf.
    # Each tool's `tool` field tells the three apart.
    call: DocumentsTool | KeyAttributeTool | FindingsTool


TOOL_PROMPT = """Choose the one database query that answers the question, and fill in its arguments.
Key attribute names: {attributes}. Today is {today}.
Document type and vendor/component restrictions are applied for you; don't repeat them."""


def choose_tool(session: Session, question: str) -> DocumentsTool | KeyAttributeTool | FindingsTool:
    attributes = ", ".join(session.scalars(select(KeyAttribute.name).where(KeyAttribute.active)))
    result = structured_llm(LlmTask.CHOOSE_QUERY_TOOL, ToolChoice).invoke([
        ("system", TOOL_PROMPT.format(attributes=attributes, today=date.today().isoformat())),
        ("human", question),
    ])
    return result.call


# =============================================================================
# Running them
# =============================================================================


def scoped_documents(scope: Scope, include_superseded: bool = False) -> Select:
    """Documents in the question's scope (vendor, component, type)."""
    query = select(Document.id).join(VendorFile, Document.vendor_file_id == VendorFile.id)
    if scope.component_ids:
        query = query.where(VendorFile.component_id.in_(scope.component_ids))
    if scope.vendor_ids:
        query = query.join(Component, VendorFile.component_id == Component.id).where(Component.vendor_id.in_(scope.vendor_ids))
    if scope.document_type_names:
        query = query.join(DocumentType, Document.document_type_id == DocumentType.id).where(
            DocumentType.name.in_(scope.document_type_names)
        )
    if not include_superseded:
        query = query.where(VendorFile.superseded_by_id.is_(None))
    return query


def document_record(context: Any) -> str:
    governing = f"governing date {context.governing_date:%d-%b-%Y}" if context.governing_date else "no governing date"
    flags = " SUPERSEDED." if context.superseded else ""
    return f"{context.label}: status {context.status.value.replace('_', ' ')}, {governing}.{flags} {context.status_reason or ''}".strip()


def open_findings_by_document(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Each document's open findings as short text: 'Compliance Bulletin review age: stale'."""
    findings = session.scalars(
        select(ComplianceFinding)
        .where(ComplianceFinding.document_id.in_(document_ids), ComplianceFinding.resolved.is_(False))
        .options(selectinload(ComplianceFinding.rule_version))
    )
    by_document: dict[uuid.UUID, list[str]] = {}
    for finding in findings:
        by_document.setdefault(finding.document_id, []).append(
            f"{finding.rule_version.name}: {finding.status.value.replace('_', ' ')}"
        )
    return by_document


def run_documents(session: Session, call: DocumentsTool, scope: Scope) -> tuple[list[Source], str]:
    query = scoped_documents(scope, call.include_superseded)
    if call.statuses:
        # A document's overall status is its WORST finding, so a stale bulletin with
        # open review items shows "needs review". Asking for "stale" must still find
        # it: match the overall status OR any open finding with that status.
        flagged = select(ComplianceFinding.document_id).where(
            ComplianceFinding.resolved.is_(False), ComplianceFinding.status.in_(call.statuses)
        )
        query = query.where(Document.compliance_status.in_(call.statuses) | Document.id.in_(flagged))
    if call.governing_before:
        query = query.where(Document.governing_date < call.governing_before)
    if call.governing_after:
        query = query.where(Document.governing_date > call.governing_after)
    ids = list(session.scalars(query))
    contexts = document_contexts(session, ids[:MAX_RECORDS])
    findings = open_findings_by_document(session, list(contexts))
    sources = [
        Source(kind="record", text=document_record(c) + (" Open findings: " + "; ".join(findings[c.document_id]) + "." if c.document_id in findings else ""), context=c)
        for c in contexts.values()
    ]
    summary = f"{len(ids)} document(s) match" + (f"; the first {MAX_RECORDS} are listed" if len(ids) > MAX_RECORDS else "")
    return sources, summary


def run_key_attribute(session: Session, call: KeyAttributeTool, scope: Scope) -> tuple[list[Source], str]:
    rows = session.execute(
        select(DocumentAttribute)
        .join(KeyAttribute, DocumentAttribute.key_attribute_id == KeyAttribute.id)
        .where(KeyAttribute.name == call.attribute, DocumentAttribute.document_id.in_(scoped_documents(scope)))
        .options(selectinload(DocumentAttribute.key_attribute))
    ).scalars().all()
    if call.only_not_stated:
        rows = [row for row in rows if row.value is None]
    contexts = document_contexts(session, [row.document_id for row in rows])
    sources = [
        Source(
            kind="record",
            text=f"{row.key_attribute.display_name}: {'NOT STATED in this document' if row.value is None else row.value}"
            + (f' (evidence: "{row.evidence_snippet}")' if row.evidence_snippet else ""),
            context=contexts[row.document_id],
            page_start=row.page_number,
            page_end=row.page_number,
        )
        for row in rows[:MAX_RECORDS]
    ]
    return sources, f"{len(rows)} document(s) have a recorded '{call.attribute}'"