"""The checks the rules engine knows (Feature 7): one parameter model and one check per kind.

QA configures rules as instances of these kinds (stored in compliance_rules);
a new kind of check is new code here. Checks are pure functions of the facts
they're given (no database), so each can be tested on its own.
"""

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.compliance import RuleKind
from src.models.document import ComplianceStatus, DateType
from src.models.review import ReviewItemKind

MONTHS_PER_YEAR = 12


# =============================================================================
# Facts: what a check may look at
# =============================================================================


@dataclass(frozen=True)
class DateFact:
    date_type: DateType
    value: date
    page_number: int
    original_text: str
    # False = mentioned by the document ("supersedes Rev. 10 (2019)"), not about it.
    is_document_date: bool


@dataclass(frozen=True)
class AttributeFact:
    name: str
    display_name: str
    value: Any  # None = not stated
    page_number: int | None


@dataclass(frozen=True)
class ReviewFact:
    kind: ReviewItemKind
    reason: str
    page_number: int | None


@dataclass(frozen=True)
class DocumentFacts:
    document_type: str  # name, e.g. "compliance_bulletin"
    document_type_label: str  # display name, e.g. "Compliance Bulletin"
    dates: list[DateFact]
    attributes: dict[str, AttributeFact]  # by key attribute name
    open_reviews: list[ReviewFact]


@dataclass(frozen=True)
class ComponentDocument:
    document_type: str
    document_type_label: str
    status: ComplianceStatus
    title: str | None


@dataclass(frozen=True)
class ComponentFacts:
    name: str
    # Documents of the component's current file (status already evaluated).
    current_documents: list[ComponentDocument]
    # Document type name -> label, for types found only in superseded files.
    superseded_types: dict[str, str]
    document_type_labels: dict[str, str]  # every known type, for messages


@dataclass
class Outcome:
    """What a check concluded. A check returns None when it has nothing to say."""

    status: ComplianceStatus
    message: str  # one sentence a user can read (Feature 7)
    governing_date: date | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def label(date_type: DateType) -> str:
    return date_type.value.replace("_", " ")


def add_months(day: date, months: int) -> date:
    """30 Jun 2022 + 36 months = 30 Jun 2025; 31 Jan + 1 month = 28/29 Feb."""
    years, month_index = divmod(day.month - 1 + months, MONTHS_PER_YEAR)
    year, month = day.year + years, month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class RuleParameters(BaseModel):
    # Unknown keys are refused, so a typo in a rule ("treshold") is an error, not ignored.
    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Document-level kinds
# =============================================================================


class DocumentAgeParameters(RuleParameters):
    governing_date_types: list[DateType] = Field(
        min_length=1,
        description="Date types that can govern the document's age; the latest one found is used, "
        "e.g. ['signature', 'revision'].",
    )
    include_referenced_dates: bool = Field(
        default=False,
        description="Also use dates the document mentions rather than its own, e.g. a certificate's "
        "lot manufacturing dates.",
    )
    threshold_months: int = Field(default=36, gt=0, description="Age at which the document is stale.")
    warning_months: int = Field(
        default=6, ge=0, description="How long before the threshold it becomes 'approaching review'."
    )


def check_document_age(facts: DocumentFacts, parameters: DocumentAgeParameters, today: date) -> Outcome:
    """Current / approaching review / stale, from the governing date (always returns an outcome)."""
    candidates = [
        fact
        for fact in facts.dates
        if fact.date_type in parameters.governing_date_types
        and (fact.is_document_date or parameters.include_referenced_dates)
    ]
    wanted = " or ".join(label(t) for t in parameters.governing_date_types)
    if not candidates:
        return Outcome(ComplianceStatus.NEEDS_REVIEW, f"No {wanted} date was found to judge the document's age.")

    governing = max(candidates, key=lambda fact: fact.value)
    due = add_months(governing.value, parameters.threshold_months)
    warn_from = add_months(governing.value, parameters.threshold_months - parameters.warning_months)
    evidence = {
        "date_type": governing.date_type.value,
        "date": governing.value.isoformat(),
        "original_text": governing.original_text,
        "page": governing.page_number,
        "review_due": due.isoformat(),
    }
    since = f"{label(governing.date_type).capitalize()} date {governing.value:%d-%b-%Y} (page {governing.page_number})"
    limit = f"the {parameters.threshold_months}-month review threshold"
    if today >= due:
        status, message = ComplianceStatus.STALE, f"{since} exceeds {limit}; review was due {due:%d-%b-%Y}."
    elif today >= warn_from:
        status, message = ComplianceStatus.APPROACHING_REVIEW, f"{since} reaches {limit} on {due:%d-%b-%Y}."
    else:
        status, message = ComplianceStatus.CURRENT, f"{since} is within {limit} (due {due:%d-%b-%Y})."
    return Outcome(status, message, governing_date=governing.value, evidence=evidence)


class MissingFieldParameters(RuleParameters):
    key_attributes: list[str] = Field(
        default_factory=list,
        description="Key attribute names that must be stated. Empty = every attribute marked required.",
    )
    date_types: list[DateType] = Field(
        default_factory=list, description="Date types the document must state about itself, e.g. ['issue']."
    )


def check_missing_field(facts: DocumentFacts, parameters: MissingFieldParameters, today: date) -> Outcome | None:
    if parameters.key_attributes:
        missing = [
            facts.attributes[name].display_name if name in facts.attributes else name
            for name in parameters.key_attributes
            if name not in facts.attributes or facts.attributes[name].value is None
        ]
    else:
        # Extraction writes a "not stated" row (value None) for every required attribute it couldn't find.
        missing = [fact.display_name for fact in facts.attributes.values() if fact.value is None]
    own_types = {fact.date_type for fact in facts.dates if fact.is_document_date}
    missing += [f"{label(t)} date" for t in parameters.date_types if t not in own_types]
    if not missing:
        return None
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"Required information not stated: {', '.join(missing)}.",
        evidence={"missing": missing},
    )


class RecordCompletenessParameters(RuleParameters):
    attribute: str = Field(description="A key attribute of value type 'records', e.g. 'lots'.")
    fields: list[str] = Field(
        min_length=1, description="Fields every record must have, e.g. ['lot_number', 'manufacturing_date']."
    )


def check_record_completeness(
    facts: DocumentFacts, parameters: RecordCompletenessParameters, today: date
) -> Outcome | None:
    """Each record (e.g. each lot) must carry every listed field."""
    fact = facts.attributes.get(parameters.attribute)
    if fact is None or not fact.value:
        return None  # not stated at all: the missing-field rule reports that
    incomplete = [
        {"record": record, "missing": [name for name in parameters.fields if not str(record.get(name) or "").strip()]}
        for record in fact.value
    ]
    incomplete = [item for item in incomplete if item["missing"]]
    if not incomplete:
        return None
    examples = "; ".join(
        f"{', '.join(f'{k}={v}' for k, v in item['record'].items() if v)} lacks {', '.join(item['missing'])}"
        for item in incomplete[:3]
    )
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"{len(incomplete)} of {len(fact.value)} {fact.display_name.lower()} records are incomplete "
        f"(page {fact.page_number}): {examples}.",
        evidence={"page": fact.page_number, "incomplete": incomplete},
    )


class DateOrder(RuleParameters):
    date_type: DateType
    not_after: DateType


class DateConflictParameters(RuleParameters):
    never_future: list[DateType] = Field(
        default_factory=list, description="Date types that can't be later than today."
    )
    order: list[DateOrder] = Field(
        default_factory=list,
        description="Pairs that must be in order: the latest `date_type` date may not be later than "
        "the latest `not_after` date, e.g. issue not after signature.",
    )


def check_date_conflict(facts: DocumentFacts, parameters: DateConflictParameters, today: date) -> Outcome | None:
    own = [fact for fact in facts.dates if fact.is_document_date]
    problems = [
        f"{label(fact.date_type)} date {fact.value:%d-%b-%Y} (page {fact.page_number}) is in the future"
        for fact in own
        if fact.date_type in parameters.never_future and fact.value > today
    ]
    for pair in parameters.order:
        first = [fact for fact in own if fact.date_type == pair.date_type]
        second = [fact for fact in own if fact.date_type == pair.not_after]
        if first and second:
            latest_first = max(first, key=lambda fact: fact.value)
            latest_second = max(second, key=lambda fact: fact.value)
            if latest_first.value > latest_second.value:
                problems.append(
                    f"{label(pair.date_type)} date {latest_first.value:%d-%b-%Y} (page {latest_first.page_number}) "
                    f"is after the {label(pair.not_after)} date {latest_second.value:%d-%b-%Y} "
                    f"(page {latest_second.page_number})"
                )
    if not problems:
        return None
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"Conflicting dates: {'; '.join(problems)}.",
        evidence={"problems": problems},
    )


class LowConfidenceParameters(RuleParameters):
    review_kinds: list[ReviewItemKind] = Field(
        default_factory=list, description="Review item kinds that count. Empty = all."
    )


def check_low_confidence(facts: DocumentFacts, parameters: LowConfidenceParameters, today: date) -> Outcome | None:
    """Anything about the document still waiting for a person means its status can't be trusted yet."""
    waiting = [
        review for review in facts.open_reviews if not parameters.review_kinds or review.kind in parameters.review_kinds
    ]
    if not waiting:
        return None
    kinds = sorted({review.kind.value.replace("_", " ") for review in waiting})
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"{len(waiting)} uncertain result(s) await human review ({', '.join(kinds)}).",
        evidence={"reviews": [{"kind": r.kind.value, "page": r.page_number, "reason": r.reason} for r in waiting]},
    )


# =============================================================================
# Component-level kinds
# =============================================================================


class MissingDocumentParameters(RuleParameters):
    document_types: list[str] = Field(
        min_length=1, description="Document type names every component must have, e.g. ['quality_certificate']."
    )
    must_be_current: list[str] = Field(
        default_factory=list,
        description="Of those, the types whose document must also have status 'current'.",
    )


def check_missing_document(
    facts: ComponentFacts, parameters: MissingDocumentParameters, today: date
) -> Outcome | None:
    by_type: dict[str, list[ComponentDocument]] = {}
    for document in facts.current_documents:
        by_type.setdefault(document.document_type, []).append(document)
    missing = [facts.document_type_labels.get(t, t) for t in parameters.document_types if t not in by_type]
    not_current = [
        f"{facts.document_type_labels.get(t, t)} ({', '.join(d.status.value.replace('_', ' ') for d in by_type[t])})"
        for t in parameters.must_be_current
        if t in by_type and not any(d.status == ComplianceStatus.CURRENT for d in by_type[t])
    ]
    if not missing and not not_current:
        return None
    parts = ([f"missing {', '.join(missing)}"] if missing else []) + (
        [f"no current {', '.join(not_current)}"] if not_current else []
    )
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"{facts.name}: {'; '.join(parts)}.",
        evidence={"missing": missing, "not_current": not_current},
    )


class RevisionWithoutReplacementParameters(RuleParameters):
    document_types: list[str] = Field(
        default_factory=list, description="Document type names to check. Empty = every type."
    )


def check_revision_without_replacement(
    facts: ComponentFacts, parameters: RevisionWithoutReplacementParameters, today: date
) -> Outcome | None:
    """A type in an older (superseded) file that the current file no longer has."""
    current_types = {document.document_type for document in facts.current_documents}
    dropped = [
        label_
        for name, label_ in sorted(facts.superseded_types.items())
        if name not in current_types and (not parameters.document_types or name in parameters.document_types)
    ]
    if not dropped:
        return None
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"{facts.name}: an older {', '.join(dropped)} exists, but the current file has no replacement.",
        evidence={"document_types": dropped},
    )


# =============================================================================
# The registry: everything the engine and the API need to know about each kind
# =============================================================================


@dataclass(frozen=True)
class RuleKindSpec:
    level: Literal["document", "component"]
    parameters: type[RuleParameters]
    check: Callable[..., Outcome | None]
    description: str


RULE_KINDS: dict[RuleKind, RuleKindSpec] = {
    RuleKind.DOCUMENT_AGE: RuleKindSpec(
        "document", DocumentAgeParameters, check_document_age,
        "Current, approaching review or stale, from the latest governing date. For one document type, "
        "a type's own age rules replace the default (all-types) one.",
    ),
    RuleKind.MISSING_FIELD: RuleKindSpec(
        "document", MissingFieldParameters, check_missing_field,
        "Flags documents that don't state required key attributes or dates.",
    ),
    RuleKind.RECORD_COMPLETENESS: RuleKindSpec(
        "document", RecordCompletenessParameters, check_record_completeness,
        "Flags records (e.g. lots) missing a required field (e.g. manufacturing date).",
    ),
    RuleKind.DATE_CONFLICT: RuleKindSpec(
        "document", DateConflictParameters, check_date_conflict,
        "Flags impossible future dates and dates in the wrong order.",
    ),
    RuleKind.LOW_CONFIDENCE: RuleKindSpec(
        "document", LowConfidenceParameters, check_low_confidence,
        "Flags documents with uncertain results still waiting in the review queue.",
    ),
    RuleKind.MISSING_DOCUMENT: RuleKindSpec(
        "component", MissingDocumentParameters, check_missing_document,
        "Flags components missing a required document type, or whose required document isn't current.",
    ),
    RuleKind.REVISION_WITHOUT_REPLACEMENT: RuleKindSpec(
        "component", RevisionWithoutReplacementParameters, check_revision_without_replacement,
        "Flags document types present in a component's older file but missing from its current one.",
    ),
}
