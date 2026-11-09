"""What a rule will really do, in words, built from the structured rule itself.

This is what QA reads before signing. It must never come from the LLM: a model
that misunderstood a policy would describe its mistake in reassuring words.
"""

from dataclasses import dataclass
from typing import Any

from src.compliance.conditions import (
    AllOf,
    AnyOf,
    AttributeCondition,
    Comparison,
    DateCondition,
    DocumentComparison,
    DocumentCondition,
    DocumentField,
    NotCondition,
    expectation,
)
from src.compliance.facts import label
from src.compliance.rule_kinds import (
    ConditionParameters,
    DateConflictParameters,
    DocumentAgeParameters,
    ManualCheckParameters,
)
from src.industry.profile import Profile
from src.models.compliance import RuleLevel


@dataclass(frozen=True)
class Names:
    """Display names, so the read-back speaks QA's language rather than ours."""

    attributes: dict[str, str]
    document_types: dict[str, str]
    profile: Profile

    def attribute(self, name: str) -> str:
        return self.attributes.get(name, name)

    def document_type(self, name: str | None) -> str:
        return self.document_types.get(name, name) if name else "document"


def worded(condition: Comparison, requirement: bool) -> str:
    """'must be at least 5' in a requirement, 'is at least 5' in a when."""
    text = expectation(condition)
    if requirement:
        return text
    return text.replace("must be", "is", 1).replace("must contain", "contains", 1)


def field_name(wanted: DocumentField, names: Names) -> str:
    if wanted.date_type is not None:
        name = f"{label(wanted.date_type)} date"
    else:
        name = names.attribute(wanted.attribute)
        name = f"{name} ({wanted.record_field})" if wanted.record_field else name
    return f"{name} on {names.document_type(wanted.document_type)}"


def describe_comparison(condition: DocumentComparison, names: Names, requirement: bool) -> str:
    left, right = field_name(condition.left, names), field_name(condition.right, names)
    if condition.relation == "equal":
        return f"{left} {'must match' if requirement else 'matches'} {right}"
    if condition.relation == "all_in":
        return f"every {left} {'must appear' if requirement else 'appears'} in {right}"
    return f"{left} {'must not be' if requirement else 'is not'} after {right}"


def describe(condition: Any, names: Names, requirement: bool = True) -> str:
    if isinstance(condition, AllOf | AnyOf):
        joiner = " AND " if isinstance(condition, AllOf) else " OR "
        parts = [describe(child, names, requirement) for child in condition.conditions]
        return parts[0] if len(parts) == 1 else "(" + joiner.join(parts) + ")"
    if isinstance(condition, NotCondition):
        return f"NOT ({describe(condition.condition, names, False)})"
    if isinstance(condition, DocumentComparison):
        return describe_comparison(condition, names, requirement)
    if isinstance(condition, AttributeCondition):
        name = names.attribute(condition.attribute)
        if condition.record_field:
            rows = "every row" if condition.records == "every" else "at least one row"
            return f"{name}, {rows}: {condition.record_field} {worded(condition, requirement)}"
        return f"{name} {worded(condition, requirement)}"
    if isinstance(condition, DateCondition):
        which = "date (own or mentioned)" if condition.include_referenced_dates else "date"
        return f"the latest {label(condition.date_type)} {which} {worded(condition, requirement)}"
    assert isinstance(condition, DocumentCondition)
    wanted = names.document_type(condition.document_type)
    wanted = f"valid (current or approaching review) {wanted}" if condition.must_be_valid else wanted
    article = "an" if wanted[0].casefold() in "aeiou" else "a"
    if condition.where is None:
        return f"has {article} {wanted}"
    return f"has {article} {wanted} where {describe(condition.where, names, requirement)}"


def uses_comparison(condition: Any) -> bool:
    if isinstance(condition, AllOf | AnyOf):
        return any(uses_comparison(child) for child in condition.conditions)
    if isinstance(condition, NotCondition):
        return uses_comparison(condition.condition)
    return isinstance(condition, DocumentComparison)


def subject(level: RuleLevel, document_type: str | None, names: Names) -> str:
    if level == RuleLevel.VENDOR:
        return f"every {names.profile.vendor_label}"
    if level == RuleLevel.COMPONENT:
        return f"every {names.profile.component_label}"
    return f"every {names.document_type(document_type)}" if document_type else "every document"


def read_back(level: RuleLevel, document_type: str | None, parameters: Any, severity: str, names: Names) -> str:
    who = subject(level, document_type, names)
    if isinstance(parameters, ManualCheckParameters):
        return (
            f"Manual check for {who}: {parameters.instructions} "
            "This is recorded for people to carry out; the system will not judge it or change any status."
        )
    if isinstance(parameters, DocumentAgeParameters):
        dates = [f"{label(t)} date" for t in parameters.governing_date_types]
        dates += [names.attribute(name) for name in parameters.governing_attributes]
        warning = (
            f"approaching review {parameters.warning_months} months before that"
            if parameters.warning_months
            else "no early warning"
        )
        text = (
            f"For {who}: age is judged from the latest of {', '.join(dates)}. "
            f"Stale at {parameters.threshold_months} months, {warning}."
        )
        if parameters.include_referenced_dates:
            text += " Dates the document only mentions also count."
        if parameters.use_stated_expiry:
            text += " A stated expiry date is used instead when there is one."
        if document_type:
            text += " This replaces the default age rule for this document type."
        return text
    if isinstance(parameters, DateConflictParameters):
        checks = [f"{label(t)} date must not be in the future" for t in parameters.never_future]
        checks += [f"{label(p.date_type)} date must not be after {label(p.not_after)} date" for p in parameters.order]
        return f"For {who}: {'; '.join(checks)}. A conflict is reported as needs review ({severity})."
    assert isinstance(parameters, ConditionParameters)
    text = f"For {who}"
    if parameters.when is not None:
        text += f", when {describe(parameters.when, names, False)}"
    text += f": {describe(parameters.require, names)}."
    if parameters.when is not None:
        text += (
            " If a document doesn't state whether this applies, it is sent for review."
            if parameters.when_unknown == "review"
            else " If a document doesn't state whether this applies, the rule is skipped."
        )
    text += f" A failure is reported as needs review ({severity}); a value that isn't stated is too."
    if uses_comparison(parameters.when) or uses_comparison(parameters.require):
        text += (
            " Values are compared ignoring case, spaces and punctuation, across all current documents of each"
            " type. If the first document isn't on file there is nothing to compare, so nothing is reported."
        )
    return text
