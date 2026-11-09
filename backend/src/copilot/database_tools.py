import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from src.copilot.source import Source, document_contexts
from src.copilot.understanding import Scope
from src.llm.models import LlmTask, embedding_model, structured_llm
from src.models import (
    Chunk,
    ComplianceFinding,
    Component,
    Document,
    DocumentAttribute,
    DocumentType,
    KeyAttribute,
    Page,
)
from src.models.document import ComplianceStatus
from src.retrieval.search import SearchFilters, hybrid_search

MAX_RECORDS = 25  # rows given to the answer; counts are exact whatever this is
CROSS_DOCUMENT_LIMIT = 8  # documents read one by one on the cross-document route
# Per document: enough that the passage that answers isn't crowded out by sections that only
# share its words (an SDS's Sections 15-16 also say "Hazard Classification"; Section 2 answers).
PASSAGES_PER_DOCUMENT = 4


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


CROSS_DOCUMENT_PROMPT = """Choose which documents must be read to answer the question: fill in the
filters the question states (status, age), and nothing else. action is "list". Today is {today}.
"Outdated", "old", "expired" or "out of date" means status stale (past its review date);
"needs review" is a different status: uncertain results waiting for a person.
Document type and vendor/component restrictions are applied for you; don't repeat them."""

TOOL_PROMPT = """Choose the one database query that answers the question, and fill in its arguments.
Key attribute names: {attributes}. Today is {today}.
"Outdated", "old", "expired" or "out of date" means status stale (past its review date);
"needs review" is a different status: uncertain results waiting for a person.
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
    query = select(Document.id)
    if scope.component_ids:
        query = query.where(Document.component_id.in_(scope.component_ids))
    if scope.vendor_ids:
        query = query.where(Document.vendor_id.in_(scope.vendor_ids))
    if scope.document_type_names:
        query = query.join(DocumentType, Document.document_type_id == DocumentType.id).where(
            DocumentType.name.in_(scope.document_type_names)
        )
    if not include_superseded:
        query = query.where(Document.superseded_by_id.is_(None))
    return query


def document_record(context: Any) -> str:
    governing = f"governing date {context.governing_date:%d-%b-%Y}" if context.governing_date else "no governing date"
    flags = " SUPERSEDED." if context.superseded else ""
    return f"{context.label}: status {context.status.value.replace('_', ' ')}, {governing}.{flags} {context.status_reason or ''}".strip()


HEADING_CHARS = 140


def first_heading(text: str) -> str | None:
    """The first meaningful line of a page: usually the product and part the document is about
    ("3M Scotch-Weld Epoxy Adhesive DP420 Black, part A"). Rules and page counters are skipped."""
    for line in text.splitlines():
        line = " ".join(line.split())
        if len(line) >= 6 and any(ch.isalpha() for ch in line) and not set(line) <= set("_-=. "):
            return line[:HEADING_CHARS]
    return None


def document_identities(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """What tells documents of the same type apart: number, revision, title, and the heading
    printed on the first page. Without it, two Safety Data Sheets (Part A and Part B) read
    the same, and an answer can't say which value belongs to which."""
    rows = session.execute(
        select(Document.id, Document.document_number, Document.revision, Document.title, Page.text)
        .outerjoin(Page, (Page.vendor_file_id == Document.vendor_file_id) & (Page.page_number == Document.start_page))
        .where(Document.id.in_(document_ids))
    ).all()
    out = {}
    for document_id, number, revision, title, first_page in rows:
        parts = []
        if number:
            parts.append(f"document number {number}")
        if revision:
            parts.append(f"revision/version {revision}")
        if title:
            parts.append(f"title “{title}”")
        heading = first_heading(first_page or "")
        if heading and (not title or heading.casefold() != title.casefold()):
            parts.append(f"first-page heading “{heading}”")
        if parts:
            out[document_id] = "Document: " + ", ".join(parts) + "."
    return out


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


def document_sections(session: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Each document's section names in page order: what it covers ('4 NATURAL RUBBER LATEX', '6 ROHS')."""
    rows = session.execute(
        select(Chunk.document_id, Chunk.section_name)
        .where(Chunk.document_id.in_(document_ids), Chunk.section_name.is_not(None))
        .group_by(Chunk.document_id, Chunk.section_name)
        .order_by(Chunk.document_id, func.min(Chunk.page_start))
    )
    sections: dict[uuid.UUID, list[str]] = {}
    for document_id, name in rows:
        sections.setdefault(document_id, []).append(name)
    return sections


def matching_documents(session: Session, call: DocumentsTool, scope: Scope) -> list[uuid.UUID]:
    """The documents a DocumentsTool call selects, oldest governing date first (undated last)."""
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
    return list(session.scalars(query.order_by(Document.governing_date.asc().nulls_last())))


def age_summary(contexts: list[Any]) -> str:
    """Oldest and newest stated outright: 'which is oldest' then has a source to cite."""
    dated = [c for c in contexts if c.governing_date]
    if not dated:
        return " None has a governing date."
    oldest, newest = dated[0], dated[-1]
    text = f" Listed oldest first by governing date. Oldest: {oldest.label} ({oldest.governing_date:%d-%b-%Y})."
    if newest is not oldest:
        text += f" Newest: {newest.label} ({newest.governing_date:%d-%b-%Y})."
    undated = len(contexts) - len(dated)
    return text + (f" {undated} have no governing date." if undated else "")


def run_documents(session: Session, call: DocumentsTool, scope: Scope) -> tuple[list[Source], str]:
    ids = matching_documents(session, call, scope)
    by_id = document_contexts(session, ids[:MAX_RECORDS])
    contexts = [by_id[i] for i in ids[:MAX_RECORDS] if i in by_id]
    findings = open_findings_by_document(session, ids[:MAX_RECORDS])
    sections = document_sections(session, ids[:MAX_RECORDS])
    identities = document_identities(session, ids[:MAX_RECORDS])
    sources = []
    for c in contexts:
        text = document_record(c)
        if c.document_id in identities:
            text += " " + identities[c.document_id]
        if c.document_id in findings:
            text += " Open findings: " + "; ".join(findings[c.document_id]) + "."
        if c.document_id in sections:
            text += " Sections: " + "; ".join(sections[c.document_id]) + "."
        sources.append(Source(kind="record", text=text, context=c))
    summary = f"{len(ids)} document(s) match" + (f"; the first {MAX_RECORDS} are listed" if len(ids) > MAX_RECORDS else "")
    return sources, summary + age_summary(contexts)


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
    identities = document_identities(session, [row.document_id for row in rows[:MAX_RECORDS]])
    sources = [
        Source(
            kind="record",
            text=f"{row.key_attribute.display_name}: {'NOT STATED in this document' if row.value is None else row.value}"
            + (f' (evidence: "{row.evidence_snippet}")' if row.evidence_snippet else "")
            + (f" {identities[row.document_id]}" if row.document_id in identities else ""),
            context=contexts[row.document_id],
            page_start=row.page_number,
            page_end=row.page_number,
        )
        for row in rows[:MAX_RECORDS]
    ]
    stated = sum(row.value is not None for row in rows)
    return sources, f"{stated} of {len(rows)} document(s) checked state '{call.attribute}'"


def run_findings(session: Session, call: FindingsTool, scope: Scope) -> tuple[list[Source], str]:
    in_scope = ComplianceFinding.document_id.in_(scoped_documents(scope))
    # Component and vendor findings ("no current bulletin") belong to what was asked
    # about: named components, the named vendors and their components, or all when
    # nothing is named.
    if scope.component_ids:
        in_scope = in_scope | ComplianceFinding.component_id.in_(scope.component_ids)
    elif scope.vendor_ids:
        vendor_components = select(Component.id).where(Component.vendor_id.in_(scope.vendor_ids))
        in_scope = (
            in_scope
            | ComplianceFinding.component_id.in_(vendor_components)
            | ComplianceFinding.vendor_id.in_(scope.vendor_ids)
        )
    else:
        in_scope = in_scope | ComplianceFinding.component_id.is_not(None) | ComplianceFinding.vendor_id.is_not(None)
    query = (
        select(ComplianceFinding)
        .where(ComplianceFinding.resolved.is_(False), in_scope)
        .options(selectinload(ComplianceFinding.rule_version))
        .order_by(ComplianceFinding.created_at)
    )
    if call.statuses:
        query = query.where(ComplianceFinding.status.in_(call.statuses))
    findings = session.scalars(query).all()
    contexts = document_contexts(session, [f.document_id for f in findings if f.document_id])
    sources = [
        Source(
            kind="finding",
            text=f"Check '{f.rule_version.name}' ({f.rule_code}, version {f.rule_version.version}, {f.severity.value}): "
            f"{f.status.value.replace('_', ' ')}. {f.message}",
            context=contexts.get(f.document_id) if f.document_id else None,
        )
        for f in findings[:MAX_RECORDS]
    ]
    return sources, f"{len(findings)} open finding(s) in total on the documents, components and vendors asked about"


def run_tool(session: Session, call: Any, scope: Scope) -> tuple[list[Source], str]:
    if isinstance(call, DocumentsTool):
        return run_documents(session, call, scope)
    if isinstance(call, KeyAttributeTool):
        return run_key_attribute(session, call, scope)
    return run_findings(session, call, scope)

def choose_documents(question: str) -> DocumentsTool:
    """Cross-document route: the status and age filters the question states ("outdated", "older than 3 years")."""
    return structured_llm(LlmTask.CHOOSE_QUERY_TOOL, DocumentsTool).invoke([
        ("system", CROSS_DOCUMENT_PROMPT.format(today=date.today().isoformat())),
        ("human", question),
    ])


RELEVANCE_CANDIDATES = 60  # chunks searched to rank documents by relevance


def by_relevance(session: Session, ids: list[uuid.UUID], text: str, vector: list[float], scope: Scope) -> list[uuid.UUID]:
    """The same documents, those whose best chunk ranks highest for `text` first; the rest keep their order."""
    allowed = set(ids)
    filters = SearchFilters(document_type_names=scope.document_type_names)
    ranked: list[uuid.UUID] = []
    for hit in hybrid_search(session, text, filters, limit=RELEVANCE_CANDIDATES, vector=vector):
        if hit.chunk.document_id in allowed and hit.chunk.document_id not in ranked:
            ranked.append(hit.chunk.document_id)
    return ranked + [i for i in ids if i not in set(ranked)]


def read_each_document(
    session: Session, question: str, topic: str, scope: Scope, search: str | None = None
) -> tuple[list[Source], str, DocumentsTool]:
    """Cross-document route: the documents the question selects (database), then each one's best passages.

    No reranking here (it would be one extra GPT call per document); the
    answer step and the grounding check still judge every passage.
    """
    call = choose_documents(question)
    ids = matching_documents(session, call, scope)
    search_text = search or f"{topic} {question}"
    vector = embedding_model().embed_query(search_text)  # once, not once per document
    if len(ids) > CROSS_DOCUMENT_LIMIT and not (scope.vendor_ids or scope.component_ids):
        # Nothing narrows it to a vendor or part: read the documents whose text best
        # matches the question first, not simply the oldest. Otherwise "Part A vs Part B"
        # depends on whether those SDSs happen to fall in the first few by date.
        ids = by_relevance(session, ids, search_text, vector, scope)
    by_id = document_contexts(session, ids[:CROSS_DOCUMENT_LIMIT])
    # Which document is which (number, revision, first-page heading "... Part A"):
    # without it, comparing two same-type documents is impossible.
    identities = document_identities(session, ids[:CROSS_DOCUMENT_LIMIT])
    sources = []
    for document_id in ids[:CROSS_DOCUMENT_LIMIT]:
        context = by_id[document_id]
        record = document_record(context) + (f" {identities[document_id]}" if document_id in identities else "")
        sources.append(Source(kind="record", text=record, context=context))
        filters = SearchFilters(document_ids=[document_id])
        for hit in hybrid_search(session, search_text, filters, limit=PASSAGES_PER_DOCUMENT, vector=vector):
            sources.append(Source(kind="passage", text=hit.chunk.content, context=context, page_start=hit.chunk.page_start,
                                  page_end=hit.chunk.page_end, section=hit.chunk.section_name))
    summary = f"{len(ids)} document(s) match" + (f"; the first {CROSS_DOCUMENT_LIMIT} were read" if len(ids) > CROSS_DOCUMENT_LIMIT else "")
    return sources, summary, call