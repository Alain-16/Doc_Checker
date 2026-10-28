"""Creating and changing compliance rules: every change is a new, validated version."""

import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.compliance.rule_kinds import (
    RULE_KINDS,
    MissingDocumentParameters,
    MissingFieldParameters,
    RecordCompletenessParameters,
    RevisionWithoutReplacementParameters,
    RuleParameters,
)
from src.models import ComplianceRule, ComplianceRuleVersion, DocumentType, KeyAttribute
from src.models.compliance import AttributeValueType, FindingSeverity, RuleKind

# "COMPLIANCE_BULLETIN_AGE": capitals, digits, underscores.
RULE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class RuleError(ValueError):
    """A rule that can't be saved; the message says why, for the person editing it."""


def check_references(session: Session, parameters: RuleParameters) -> None:
    """Names in the parameters must exist: a rule about a type nobody has would never fire."""
    type_names = set(session.scalars(select(DocumentType.name)))
    referenced_types: list[str] = []
    if isinstance(parameters, MissingDocumentParameters):
        referenced_types = parameters.document_types + parameters.must_be_current
        if not set(parameters.must_be_current) <= set(parameters.document_types):
            raise RuleError("must_be_current may only list types that are also in document_types.")
    elif isinstance(parameters, RevisionWithoutReplacementParameters):
        referenced_types = parameters.document_types
    unknown_types = sorted(set(referenced_types) - type_names)
    if unknown_types:
        raise RuleError(f"Unknown document type(s): {', '.join(unknown_types)}.")

    attributes = {a.name: a for a in session.scalars(select(KeyAttribute))}
    if isinstance(parameters, MissingFieldParameters):
        unknown = sorted(set(parameters.key_attributes) - attributes.keys())
        if unknown:
            raise RuleError(f"Unknown key attribute(s): {', '.join(unknown)}.")
    if isinstance(parameters, RecordCompletenessParameters):
        attribute = attributes.get(parameters.attribute)
        if attribute is None or attribute.value_type != AttributeValueType.RECORDS:
            raise RuleError(f"'{parameters.attribute}' is not a key attribute with records.")
        unknown = sorted(set(parameters.fields) - set(attribute.record_fields))
        if unknown:
            raise RuleError(f"'{parameters.attribute}' records have no field(s): {', '.join(unknown)}.")


def validated_parameters(session: Session, kind: RuleKind, parameters: dict[str, Any]) -> dict[str, Any]:
    """Parameters checked against the kind's model, with defaults filled in, ready to store."""
    try:
        model = RULE_KINDS[kind].parameters.model_validate(parameters)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'parameters'}: {e['msg']}" for e in error.errors())
        raise RuleError(f"Invalid parameters for {kind}: {problems}") from error
    check_references(session, model)
    # Storing the full model (defaults included) means a later change of a
    # default in code never silently changes what an existing version meant.
    return model.model_dump(mode="json")


def create_rule(
    session: Session,
    *,
    code: str,
    kind: RuleKind,
    document_type: str | None,
    name: str,
    parameters: dict[str, Any],
    severity: FindingSeverity,
    active: bool,
    change_reason: str,
) -> ComplianceRule:
    if not RULE_CODE.match(code):
        raise RuleError("Code must be 3-64 capitals, digits or underscores, starting with a letter.")
    if session.scalar(select(ComplianceRule.id).where(ComplianceRule.code == code)):
        raise RuleError(f"A rule with code {code} already exists.")
    document_type_id = None
    if document_type is not None:
        if RULE_KINDS[kind].level == "component":
            raise RuleError(f"{kind} is about a whole component, so it can't be limited to one document type.")
        document_type_id = session.scalar(select(DocumentType.id).where(DocumentType.name == document_type))
        if document_type_id is None:
            raise RuleError(f"Unknown document type: {document_type}.")

    rule = ComplianceRule(code=code, kind=kind, document_type_id=document_type_id)
    rule.versions.append(
        ComplianceRuleVersion(
            version=1,
            name=name,
            parameters=validated_parameters(session, kind, parameters),
            severity=severity,
            active=active,
            change_reason=change_reason,
        )
    )
    session.add(rule)
    session.flush()
    return rule


def update_rule(
    session: Session,
    rule: ComplianceRule,
    *,
    name: str,
    parameters: dict[str, Any],
    severity: FindingSeverity,
    active: bool,
    change_reason: str,
) -> ComplianceRuleVersion:
    """Add the next version. The rule's code, kind and document type never change:
    a rule about something else is a new rule, so old findings keep their meaning."""
    version = ComplianceRuleVersion(
        version=rule.current.version + 1,
        name=name,
        parameters=validated_parameters(session, rule.kind, parameters),
        severity=severity,
        active=active,
        change_reason=change_reason,
    )
    rule.versions.append(version)
    session.flush()
    return version
