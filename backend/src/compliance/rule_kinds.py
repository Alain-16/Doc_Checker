"""The checks the rules engine knows (Feature 7): one parameter model and one check per kind.

QA configures rules as instances of these kinds (stored in compliance_rules);
a new kind of check is new code here. Checks are pure functions of the facts
they're given (no database), so each can be tested on its own.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import Field, model_validator

from src.compliance.conditions import Condition, Truth, evaluate
from src.compliance.facts import (
    DocumentFacts,
    GroupDocument,
    GroupFacts,
    Outcome,
    RuleParameters,
    add_months,
    label,
)
from src.models.compliance import RuleKind, RuleLevel
from src.models.document import ComplianceStatus, DateType
from src.models.review import ReviewItemKind

# =============================================================================
# Document-level kinds
# =============================================================================


class DocumentAgeParameters(RuleParameters):
    governing_date_types: list[DateType] = Field(
        default_factory=list,
        description="Date types that can govern the document's age; the latest one found is used, "
        "e.g. ['signature', 'revision'].",
    )
    governing_attributes: list[str] = Field(
        default_factory=list,
        description="Date key attributes that can govern it too, for dates the fixed types don't "
        "name, e.g. ['calibration_date'].",
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
    use_stated_expiry: bool = Field(
        default=False,
        description="When the document states its OWN expiry ('valid until'), judge it by that date "
        "instead of its age: stale once expired, approaching review within warning_months of it. "
        "Certificates, permits and licences carry one in every industry.",
    )

    @model_validator(mode="after")
    def has_a_governing_date(self) -> "DocumentAgeParameters":
        if not self.governing_date_types and not self.governing_attributes:
            raise ValueError("Name at least one governing date type or date attribute.")
        return self


@dataclass(frozen=True)
class GoverningDate:
    """A date that can govern age: a labelled date, or a date attribute."""

    source: str  # the date type, or the attribute's name
    name: str  # as a sentence starts it: "Signature date", "Calibration Date"
    value: date
    page_number: int | None
    original_text: str | None


def governing_candidates(facts: DocumentFacts, parameters: DocumentAgeParameters) -> list[GoverningDate]:
    candidates = [
        GoverningDate(fact.date_type.value, f"{label(fact.date_type)} date".capitalize(), fact.value, fact.page_number, fact.original_text)
        for fact in facts.dates
        if fact.date_type in parameters.governing_date_types
        and (fact.is_document_date or parameters.include_referenced_dates)
    ]
    for name in parameters.governing_attributes:
        fact = facts.attributes.get(name)
        if fact is not None and fact.value is not None:
            candidates.append(
                GoverningDate(name, fact.display_name, date.fromisoformat(fact.value), fact.page_number, fact.evidence_snippet)
            )
    return candidates


def check_stated_expiry(facts: DocumentFacts, parameters: DocumentAgeParameters, today: date) -> Outcome | None:
    """Judged by the document's own expiry date, or None when it states none."""
    expiries = [f for f in facts.dates if f.date_type == DateType.EXPIRY and f.is_document_date]
    if not expiries:
        return None
    expiry = max(expiries, key=lambda fact: fact.value)
    warn_from = add_months(expiry.value, -parameters.warning_months)
    evidence = {
        "date_type": expiry.date_type.value,
        "date": expiry.value.isoformat(),
        "original_text": expiry.original_text,
        "page": expiry.page_number,
        # Read by the "coming due" alerts, as for an age-based due date.
        "review_due": expiry.value.isoformat(),
    }
    since = f"Valid until {expiry.value:%d-%b-%Y} (page {expiry.page_number})"
    if today >= expiry.value:
        status, message = ComplianceStatus.STALE, f"{since}: the document has expired."
    elif today >= warn_from:
        status, message = ComplianceStatus.APPROACHING_REVIEW, f"{since}: expires within {parameters.warning_months} months."
    else:
        status, message = ComplianceStatus.CURRENT, f"{since}: in force."
    return Outcome(status, message, governing_date=expiry.value, evidence=evidence)


def check_document_age(facts: DocumentFacts, parameters: DocumentAgeParameters, today: date) -> Outcome:
    """Current / approaching review / stale, from the governing date (always returns an outcome)."""
    if parameters.use_stated_expiry:
        by_expiry = check_stated_expiry(facts, parameters, today)
        if by_expiry is not None:
            return by_expiry
    candidates = governing_candidates(facts, parameters)
    if not candidates:
        waiting = [name for name in parameters.governing_attributes if name not in facts.attributes]
        if waiting and not parameters.governing_date_types:
            return Outcome(
                ComplianceStatus.NEEDS_REVIEW, f"{', '.join(waiting)} not extracted yet, so the document's age can't be judged."
            )
        wanted = [f"{' or '.join(label(t) for t in parameters.governing_date_types)} date"] if parameters.governing_date_types else []
        wanted += [facts.attributes[name].display_name for name in parameters.governing_attributes if name in facts.attributes]
        return Outcome(ComplianceStatus.NEEDS_REVIEW, f"No {' or '.join(wanted)} was found to judge the document's age.")

    governing = max(candidates, key=lambda candidate: candidate.value)
    due = add_months(governing.value, parameters.threshold_months)
    warn_from = add_months(governing.value, parameters.threshold_months - parameters.warning_months)
    evidence = {
        "date_type": governing.source,
        "date": governing.value.isoformat(),
        "original_text": governing.original_text,
        "page": governing.page_number,
        "review_due": due.isoformat(),
    }
    since = f"{governing.name} {governing.value:%d-%b-%Y} (page {governing.page_number})"
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
    # No row = not extracted yet: nothing is known, so it isn't reported as missing.
    if parameters.key_attributes:
        named = [facts.attributes[name] for name in parameters.key_attributes if name in facts.attributes]
    else:
        named = [fact for fact in facts.attributes.values() if fact.required]
    missing = [fact.display_name for fact in named if fact.value is None]
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
    facts: GroupFacts, parameters: MissingDocumentParameters, today: date
) -> Outcome | None:
    by_type: dict[str, list[GroupDocument]] = {}
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
    facts: GroupFacts, parameters: RevisionWithoutReplacementParameters, today: date
) -> Outcome | None:
    """A type found only in superseded documents: no current document of that type remains.

    With per-document superseding a replaced document always has a current
    successor of its type, so this fires only if that successor was itself
    reclassified or reassigned to another component.
    """
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
        f"{facts.name}: an older {', '.join(dropped)} exists, but no current document replaces it.",
        evidence={"document_types": dropped},
    )


# =============================================================================
# Kinds for any level
# =============================================================================


class ConditionParameters(RuleParameters):
    when: Condition | None = Field(
        default=None, description="Only judge subjects where this holds. Empty = all of them."
    )
    when_unknown: Literal["skip", "review"] = Field(
        default="skip",
        description="When a subject doesn't state what `when` asks: skip it, or send it for review.",
    )
    require: Condition = Field(description="What must hold.")


def check_condition(
    facts: DocumentFacts | GroupFacts, parameters: ConditionParameters, today: date
) -> Outcome | None:
    """QA's own rule. A `when` that doesn't hold means the rule doesn't apply, and
    anything still waiting for extraction says nothing yet."""
    prefix = f"{facts.name}: " if isinstance(facts, GroupFacts) else ""
    if parameters.when is not None:
        applies = evaluate(parameters.when, facts, today)
        if applies.truth == Truth.NOT_STATED and parameters.when_unknown == "review":
            return Outcome(
                ComplianceStatus.NEEDS_REVIEW,
                f"{prefix}Can't tell whether this rule applies: {applies.detail}.",
                evidence={"result": applies.truth.value, "checks": applies.evidence},
            )
        if applies.truth != Truth.MET:
            return None
    verdict = evaluate(parameters.require, facts, today)
    if verdict.truth in (Truth.MET, Truth.PENDING):
        return None
    outcome = "can't be confirmed" if verdict.truth == Truth.NOT_STATED else "not met"
    return Outcome(
        ComplianceStatus.NEEDS_REVIEW,
        f"{prefix}Requirement {outcome}: {verdict.detail}.",
        evidence={"result": verdict.truth.value, "checks": verdict.evidence},
    )


class ManualCheckParameters(RuleParameters):
    instructions: str = Field(min_length=1, description="What a person must check, in QA's words.")


def check_manual(facts: Any, parameters: ManualCheckParameters, today: date) -> None:
    """Can't be judged from documents: recorded and signed, but never changes a status."""
    return


# =============================================================================
# The registry: everything the engine and the API need to know about each kind
# =============================================================================


@dataclass(frozen=True)
class RuleKindSpec:
    levels: tuple[RuleLevel, ...]  # the first is the default
    parameters: type[RuleParameters]
    check: Callable[..., Outcome | None]
    description: str


DOCUMENT_ONLY = (RuleLevel.DOCUMENT,)
COMPONENT_ONLY = (RuleLevel.COMPONENT,)
ANY_LEVEL = (RuleLevel.DOCUMENT, RuleLevel.COMPONENT, RuleLevel.VENDOR)

RULE_KINDS: dict[RuleKind, RuleKindSpec] = {
    RuleKind.DOCUMENT_AGE: RuleKindSpec(
        DOCUMENT_ONLY, DocumentAgeParameters, check_document_age,
        "Current, approaching review or stale, from the latest governing date. For one document type, "
        "a type's own age rules replace the default (all-types) one.",
    ),
    RuleKind.MISSING_FIELD: RuleKindSpec(
        DOCUMENT_ONLY, MissingFieldParameters, check_missing_field,
        "Flags documents that don't state required key attributes or dates.",
    ),
    RuleKind.RECORD_COMPLETENESS: RuleKindSpec(
        DOCUMENT_ONLY, RecordCompletenessParameters, check_record_completeness,
        "Flags records (e.g. lots) missing a required field (e.g. manufacturing date).",
    ),
    RuleKind.DATE_CONFLICT: RuleKindSpec(
        DOCUMENT_ONLY, DateConflictParameters, check_date_conflict,
        "Flags impossible future dates and dates in the wrong order.",
    ),
    RuleKind.LOW_CONFIDENCE: RuleKindSpec(
        DOCUMENT_ONLY, LowConfidenceParameters, check_low_confidence,
        "Flags documents with uncertain results still waiting in the review queue.",
    ),
    RuleKind.MISSING_DOCUMENT: RuleKindSpec(
        COMPONENT_ONLY, MissingDocumentParameters, check_missing_document,
        "Flags components missing a required document type, or whose required document isn't current.",
    ),
    RuleKind.REVISION_WITHOUT_REPLACEMENT: RuleKindSpec(
        COMPONENT_ONLY, RevisionWithoutReplacementParameters, check_revision_without_replacement,
        "Flags document types present in a component's older file but missing from its current one.",
    ),
    RuleKind.CONDITION: RuleKindSpec(
        ANY_LEVEL, ConditionParameters, check_condition,
        "QA's own rule: when one condition holds, another must. Conditions check attributes, dates, "
        "required documents and values across two documents, and combine with all, any and not.",
    ),
    RuleKind.MANUAL_CHECK: RuleKindSpec(
        ANY_LEVEL, ManualCheckParameters, check_manual,
        "A rule documents can't prove: recorded and signed for people to carry out, never judged here.",
    ),
}
