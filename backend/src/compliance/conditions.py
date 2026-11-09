"""Conditions: the general shape QA's rules are built from.

A rule says "when <condition>, <condition> must hold". Conditions check an
attribute, a date or a required document, and combine with all / any / not, so
a new kind of rule is new data rather than new code. Everything here is pure:
the same facts always give the same verdict.

Not every question has a yes or no. A document may not state the value, or
extraction may not have reached it yet, and those must not read as a failure,
so a verdict has four possible truths rather than two.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from src.compliance.facts import (
    AttributeFact,
    DocumentFacts,
    GroupDocument,
    GroupFacts,
    RuleParameters,
    add_months,
    label,
)
from src.models.document import ComplianceStatus, DateType

NUMBER = re.compile(r"-?\d+(\.\d+)?")
NOT_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")
MAX_VALUES_IN_MESSAGE = 5
# Still valid: "approaching review" is a warning, not a lapse.
VALID_STATUSES = (ComplianceStatus.CURRENT, ComplianceStatus.APPROACHING_REVIEW)


class Truth(Enum):
    MET = "met"
    NOT_MET = "not_met"
    NOT_STATED = "not_stated"  # extraction looked; the document doesn't say, or can't be read
    PENDING = "pending"  # not extracted yet, or never will be for this document


class Operator(StrEnum):
    STATED = "stated"
    EQUALS = "equals"
    ONE_OF = "one_of"
    CONTAINS = "contains"
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    ON_OR_AFTER = "on_or_after"
    ON_OR_BEFORE = "on_or_before"
    # A date no older than this many months.
    AGE_AT_MOST_MONTHS = "age_at_most_months"
    # A date at least this many months in the future.
    VALID_FOR_AT_LEAST_MONTHS = "valid_for_at_least_months"


# What each operator's `value` must be. STATED takes none.
TEXT_OPERATORS = {Operator.EQUALS, Operator.CONTAINS}
NUMBER_OPERATORS = {Operator.AT_LEAST, Operator.AT_MOST}
FIXED_DATE_OPERATORS = {Operator.ON_OR_AFTER, Operator.ON_OR_BEFORE}
MONTHS_OPERATORS = {Operator.AGE_AT_MOST_MONTHS, Operator.VALID_FOR_AT_LEAST_MONTHS}
DATE_OPERATORS = {Operator.STATED} | FIXED_DATE_OPERATORS | MONTHS_OPERATORS


class Comparison(RuleParameters):
    """An operator and the value it compares against."""

    operator: Operator
    value: str | float | list[str] | None = Field(
        default=None,
        description="stated: none. equals/contains: text or number. one_of: list of texts. at_least/at_most: "
        "number. on_or_after/on_or_before: YYYY-MM-DD. age_at_most_months/valid_for_at_least_months: whole months.",
    )

    @model_validator(mode="after")
    def value_fits_operator(self) -> "Comparison":
        operator, value = self.operator, self.value
        is_number = isinstance(value, int | float)
        if operator == Operator.STATED:
            valid = value is None
        elif operator == Operator.ONE_OF:
            valid = isinstance(value, list) and len(value) > 0
        elif operator in TEXT_OPERATORS:
            valid = is_number or (isinstance(value, str) and bool(value.strip()))
        elif operator in NUMBER_OPERATORS:
            valid = is_number
        elif operator in MONTHS_OPERATORS:
            valid = is_number and value > 0 and float(value).is_integer()
        else:
            valid = isinstance(value, str) and parsed_date(value) is not None
        if not valid:
            raise ValueError(f"{value!r} is not a valid value for operator {operator.value}")
        return self


class AttributeCondition(Comparison):
    """About a key attribute of the document, or the rows of a records attribute."""

    type: Literal["attribute"] = "attribute"
    attribute: str = Field(description="Key attribute name, e.g. 'liability_cover'.")
    record_field: str | None = Field(
        default=None, description="For a records attribute: the field of each row to compare, e.g. 'test_result'."
    )
    records: Literal["every", "any"] = Field(
        default="every", description="With record_field: must every row match, or at least one?"
    )


class DateCondition(Comparison):
    """About one of the document's dates; the latest of that type is used."""

    type: Literal["date"] = "date"
    date_type: DateType
    include_referenced_dates: bool = Field(
        default=False, description="Also use dates the document mentions rather than its own."
    )


class DocumentCondition(RuleParameters):
    """For a component or vendor: it must have a matching document."""

    type: Literal["document"] = "document"
    document_type: str | None = Field(default=None, description="Document type name; empty = any type.")
    must_be_valid: bool = Field(
        default=False, description="Only count documents that are current or approaching review."
    )
    where: "Condition | None" = Field(
        default=None, description="What the document itself must satisfy, e.g. its cover amount."
    )


class DocumentField(RuleParameters):
    """One value on a type of document: an attribute (or a field of its rows), or a date."""

    document_type: str
    attribute: str | None = Field(default=None, description="Key attribute name.")
    record_field: str | None = Field(default=None, description="For a records attribute: the field of each row.")
    date_type: DateType | None = Field(default=None, description="A date type, instead of an attribute.")

    @model_validator(mode="after")
    def names_one_value(self) -> "DocumentField":
        if (self.attribute is None) == (self.date_type is None):
            raise ValueError("Name an attribute or a date type, not both.")
        if self.record_field is not None and self.attribute is None:
            raise ValueError("record_field goes with an attribute.")
        return self


class DocumentComparison(RuleParameters):
    """For a component or vendor: a value on one type of document against a value on another.

    equal: the two sides hold the same values. all_in: every left value appears
    on the right. not_after: the latest left date isn't after the latest right
    date. All current documents of a type count together, so lots spread over
    two certificates are all checked.
    """

    type: Literal["compare_documents"] = "compare_documents"
    left: DocumentField
    relation: Literal["equal", "all_in", "not_after"]
    right: DocumentField


class AllOf(RuleParameters):
    type: Literal["all"] = "all"
    conditions: list["Condition"] = Field(min_length=1)


class AnyOf(RuleParameters):
    type: Literal["any"] = "any"
    conditions: list["Condition"] = Field(min_length=1)


class NotCondition(RuleParameters):
    type: Literal["not"] = "not"
    condition: "Condition"


Condition = Annotated[
    AttributeCondition | DateCondition | DocumentCondition | DocumentComparison | AllOf | AnyOf | NotCondition,
    Field(discriminator="type"),
]
for model in (DocumentCondition, AllOf, AnyOf, NotCondition):
    model.model_rebuild()


@dataclass
class Verdict:
    truth: Truth
    detail: str  # readable whichever way it went
    evidence: list[dict[str, Any]] = field(default_factory=list)


def combine(verdicts: list[Verdict], decisive: Truth, otherwise: Truth, joiner: str) -> Verdict:
    """One decisive verdict settles it, and a gap in the facts outranks a clean result.

    "all": any NOT_MET fails it, whatever else is unknown. "any": any MET
    passes it. Only when every verdict is known does `otherwise` apply.
    """
    for truth in (decisive, Truth.PENDING, Truth.NOT_STATED):
        matching = [verdict for verdict in verdicts if verdict.truth == truth]
        if matching:
            return Verdict(
                truth,
                joiner.join(verdict.detail for verdict in matching),
                [item for verdict in matching for item in verdict.evidence],
            )
    return Verdict(
        otherwise,
        joiner.join(verdict.detail for verdict in verdicts),
        [item for verdict in verdicts for item in verdict.evidence],
    )


def all_of(verdicts: list[Verdict]) -> Verdict:
    return combine(verdicts, Truth.NOT_MET, Truth.MET, "; ")


def any_of(verdicts: list[Verdict]) -> Verdict:
    return combine(verdicts, Truth.MET, Truth.NOT_MET, " or ")


def parsed_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def parsed_number(value: Any) -> float | None:
    """Stored numbers, and record cells such as "1,000,000". "5 mg" isn't one: the unit is unknown."""
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace(",", "").strip()
    return float(text) if NUMBER.fullmatch(text) else None


def squash(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def same(actual: Any, expected: Any) -> bool:
    actual_number, expected_number = parsed_number(actual), parsed_number(expected)
    if actual_number is not None and expected_number is not None:
        return actual_number == expected_number
    return squash(actual) == squash(expected)


def compare_one(operator: Operator, expected: Any, actual: Any, today: date) -> bool | None:
    """Does this value match? None = it can't be read as what the operator needs."""
    match operator:
        case Operator.STATED:
            return bool(str(actual).strip())
        case Operator.EQUALS:
            return same(actual, expected)
        case Operator.ONE_OF:
            return any(same(actual, option) for option in expected)
        case Operator.CONTAINS:
            return squash(expected) in squash(actual)
    if operator in NUMBER_OPERATORS:
        number = parsed_number(actual)
        if number is None:
            return None
        return number >= expected if operator == Operator.AT_LEAST else number <= expected
    day = parsed_date(actual)
    if day is None:
        return None
    match operator:
        case Operator.ON_OR_AFTER:
            return day >= date.fromisoformat(expected)
        case Operator.ON_OR_BEFORE:
            return day <= date.fromisoformat(expected)
        case Operator.AGE_AT_MOST_MONTHS:
            return day >= add_months(today, -int(expected))
        case _:
            return day >= add_months(today, int(expected))


def compare(condition: Comparison, actual: Any, today: date) -> bool | None:
    """A list attribute matches when one of its items does."""
    if not isinstance(actual, list):
        return compare_one(condition.operator, condition.value, actual, today)
    results = [compare_one(condition.operator, condition.value, item, today) for item in actual]
    return True if True in results else None if None in results else False


def shown(value: Any) -> Any:
    """Numbers are stored as floats: 500000, not 500000.0, in anything a person reads."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def expectation(condition: Comparison) -> str:
    """'must be at least 1000000': what the condition asks for, in words."""
    value = shown(condition.value)
    match condition.operator:
        case Operator.STATED:
            return "must be stated"
        case Operator.EQUALS:
            return f"must be {value}"
        case Operator.ONE_OF:
            return f"must be one of {', '.join(value)}"
        case Operator.CONTAINS:
            return f"must contain '{value}'"
        case Operator.AT_LEAST:
            return f"must be at least {value}"
        case Operator.AT_MOST:
            return f"must be at most {value}"
        case Operator.ON_OR_AFTER:
            return f"must be on or after {value}"
        case Operator.ON_OR_BEFORE:
            return f"must be on or before {value}"
        case Operator.AGE_AT_MOST_MONTHS:
            return f"must be no older than {value} months"
        case _:
            return f"must be at least {value} months in the future"


def truth_of(result: bool | None) -> Truth:
    return Truth.NOT_STATED if result is None else Truth.MET if result else Truth.NOT_MET


def evaluate_records(condition: AttributeCondition, fact: AttributeFact, today: date) -> Verdict:
    name = f"{fact.display_name} {condition.record_field}"
    verdicts = []
    for number, record in enumerate(fact.value, start=1):
        cell = record.get(condition.record_field) or ""
        result = compare(condition, cell, today) if str(cell).strip() or condition.operator == Operator.STATED else None
        verdicts.append(
            Verdict(
                truth_of(result),
                f"{name} in row {number} is {cell or 'empty'} (page {fact.page_number}), {expectation(condition)}",
                [{"attribute": fact.name, "row": number, "value": cell, "page": fact.page_number}],
            )
        )
    return all_of(verdicts) if condition.records == "every" else any_of(verdicts)


def evaluate_attribute(condition: AttributeCondition, facts: DocumentFacts, today: date) -> Verdict:
    fact = facts.attributes.get(condition.attribute)
    if fact is None:
        return Verdict(Truth.PENDING, f"{condition.attribute} has not been extracted")
    if fact.value is None:
        truth = Truth.NOT_MET if condition.operator == Operator.STATED else Truth.NOT_STATED
        return Verdict(truth, f"{fact.display_name} is not stated", [{"attribute": fact.name, "value": None}])
    if condition.record_field:
        return evaluate_records(condition, fact, today)
    return Verdict(
        truth_of(compare(condition, fact.value, today)),
        f"{fact.display_name} is {shown(fact.value)} (page {fact.page_number}), {expectation(condition)}",
        [{"attribute": fact.name, "value": fact.value, "page": fact.page_number, "snippet": fact.evidence_snippet}],
    )


def evaluate_date(condition: DateCondition, facts: DocumentFacts, today: date) -> Verdict:
    name = f"{label(condition.date_type)} date".capitalize()
    candidates = [
        fact
        for fact in facts.dates
        if fact.date_type == condition.date_type and (fact.is_document_date or condition.include_referenced_dates)
    ]
    if not candidates:
        truth = Truth.NOT_MET if condition.operator == Operator.STATED else Truth.NOT_STATED
        return Verdict(truth, f"{name} is not stated", [{"date_type": condition.date_type.value, "value": None}])
    latest = max(candidates, key=lambda fact: fact.value)
    return Verdict(
        truth_of(compare(condition, latest.value.isoformat(), today)),
        f"{name} is {latest.value:%d-%b-%Y} (page {latest.page_number}), {expectation(condition)}",
        [{"date_type": condition.date_type.value, "value": latest.value.isoformat(), "page": latest.page_number}],
    )


def evaluate_document(condition: DocumentCondition, facts: GroupFacts, today: date) -> Verdict:
    wanted = (
        facts.document_type_labels.get(condition.document_type, condition.document_type)
        if condition.document_type
        else "document"
    )
    wanted = f"valid {wanted}" if condition.must_be_valid else wanted

    def counts(document: GroupDocument) -> bool:
        return condition.document_type in (None, document.document_type) and (
            not condition.must_be_valid or document.status in VALID_STATUSES
        )

    documents = [document for document in facts.current_documents if counts(document)]
    if not documents:
        return Verdict(Truth.NOT_MET, f"no {wanted} found", [{"document_type": condition.document_type}])
    if condition.where is None:
        return Verdict(Truth.MET, f"has {wanted}", [{"document_type": condition.document_type}])
    return any_of([evaluate(condition.where, document.facts, today) for document in documents])


@dataclass
class Side:
    """What one side of a comparison found across its documents."""

    label: str  # "Lot Number on Quality Certificate"
    documents: int = 0
    values: list[tuple[Any, int | None]] = field(default_factory=list)  # value, page
    pending: int = 0  # documents not read for this value yet
    not_stated: int = 0  # documents that don't state it

    def gap(self) -> Truth | None:
        """Why this side might be incomplete, the most temporary reason first."""
        return Truth.PENDING if self.pending else Truth.NOT_STATED if self.not_stated else None


def read_field(wanted: DocumentField, facts: DocumentFacts, side: Side) -> None:
    if wanted.date_type is not None:
        found = [(d.value.isoformat(), d.page_number) for d in facts.dates if d.date_type == wanted.date_type and d.is_document_date]
    else:
        fact = facts.attributes.get(wanted.attribute)
        if fact is None:
            side.pending += 1
            return
        value = fact.value
        if wanted.record_field and value is not None:
            value = [record.get(wanted.record_field) for record in value]
        items = value if isinstance(value, list) else [value]
        found = [(item, fact.page_number) for item in items if item is not None and str(item).strip()]
    if found:
        side.values += found
    else:
        side.not_stated += 1


def side_of(wanted: DocumentField, facts: GroupFacts) -> Side:
    documents = [d for d in facts.current_documents if d.document_type == wanted.document_type]
    type_label = facts.document_type_labels.get(wanted.document_type, wanted.document_type)
    if wanted.date_type is not None:
        name = f"{label(wanted.date_type)} date".capitalize()
    else:
        known = [d.facts.attributes[wanted.attribute] for d in documents if wanted.attribute in d.facts.attributes]
        name = known[0].display_name if known else wanted.attribute
        name = f"{name} {wanted.record_field}" if wanted.record_field else name
    side = Side(f"{name} on {type_label}", len(documents))
    for document in documents:
        read_field(wanted, document.facts, side)
    return side


def comparable(value: Any) -> str:
    """Documents format the same value differently: "4432/50 Grey" is "4432-50 grey",
    and 1,000 is 1000. Numbers stay numbers, so 1.5 isn't mistaken for 15."""
    number = parsed_number(value)
    return str(shown(number)) if number is not None else NOT_ALPHANUMERIC.sub("", str(value).casefold())


def listed(values: list[Any]) -> str:
    shown_values = ", ".join(str(shown(value)) for value in values[:MAX_VALUES_IN_MESSAGE])
    extra = len(values) - MAX_VALUES_IN_MESSAGE
    return f"{shown_values} and {extra} more" if extra > 0 else shown_values


def evaluate_comparison(condition: DocumentComparison, facts: GroupFacts, today: date) -> Verdict:
    left, right = side_of(condition.left, facts), side_of(condition.right, facts)
    evidence = [
        {"side": side.label, "values": [{"value": v, "page": p} for v, p in side.values]} for side in (left, right)
    ]
    # Nothing on the left means nothing to check; whether the document must
    # exist at all is a document condition's job.
    if not left.documents:
        return Verdict(Truth.PENDING, f"no {left.label} to compare")
    if not left.values:
        return Verdict(left.gap(), f"{left.label} is not available to compare", evidence)
    if not right.documents:
        return Verdict(Truth.NOT_STATED, f"{left.label} has no {right.label} to compare with", evidence)
    if not right.values:
        return Verdict(right.gap(), f"{right.label} is not available to compare", evidence)

    if condition.relation == "not_after":
        left_dates = [parsed_date(value) for value, _ in left.values]
        right_dates = [parsed_date(value) for value, _ in right.values]
        if None in left_dates or None in right_dates:
            return Verdict(Truth.NOT_STATED, f"{left.label} or {right.label} can't be read as a date", evidence)
        latest_left, latest_right = max(left_dates), max(right_dates)
        holds = latest_left <= latest_right
        detail = f"{left.label} {latest_left:%d-%b-%Y} must not be after {right.label} {latest_right:%d-%b-%Y}"
        blocker = left.gap() if holds else right.gap()
        return Verdict(blocker or (Truth.MET if holds else Truth.NOT_MET), detail, evidence)

    left_values = {comparable(value): value for value, _ in left.values}
    right_values = {comparable(value): value for value, _ in right.values}
    left_values.pop("", None)
    right_values.pop("", None)
    only_left = [value for key, value in left_values.items() if key not in right_values]
    if condition.relation == "all_in":
        holds = not only_left
        detail = f"{listed(only_left)} from {left.label} not found on {right.label}" if only_left else (
            f"every {left.label} appears on {right.label}"
        )
        # Passing with an unread left document, or failing with an unread right one, proves nothing yet.
        blocker = left.gap() if holds else right.gap()
    else:
        only_right = [value for key, value in right_values.items() if key not in left_values]
        holds = not only_left and not only_right
        detail = (
            f"{left.label} matches {right.label}"
            if holds
            else f"{left.label} ({listed(list(left_values.values()))}) doesn't match "
            f"{right.label} ({listed(list(right_values.values()))})"
        )
        blocker = left.gap() or right.gap()
    return Verdict(blocker or (Truth.MET if holds else Truth.NOT_MET), detail, evidence)


def evaluate(condition: Any, facts: DocumentFacts | GroupFacts, today: date) -> Verdict:
    if isinstance(condition, AllOf):
        return all_of([evaluate(child, facts, today) for child in condition.conditions])
    if isinstance(condition, AnyOf):
        return any_of([evaluate(child, facts, today) for child in condition.conditions])
    if isinstance(condition, NotCondition):
        inner = evaluate(condition.condition, facts, today)
        swapped = {Truth.MET: Truth.NOT_MET, Truth.NOT_MET: Truth.MET}
        return Verdict(swapped.get(inner.truth, inner.truth), f"must not hold: {inner.detail}", inner.evidence)
    evaluators: dict[type, Callable[..., Verdict]] = {
        AttributeCondition: evaluate_attribute,
        DateCondition: evaluate_date,
        DocumentCondition: evaluate_document,
        DocumentComparison: evaluate_comparison,
    }
    return evaluators[type(condition)](condition, facts, today)
