"""Creating and changing compliance rules: every change is a new, validated version."""

import re
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.signatures import sign
from src.compliance.conditions import (
    DATE_OPERATORS,
    NUMBER_OPERATORS,
    AllOf,
    AnyOf,
    AttributeCondition,
    DateCondition,
    DocumentComparison,
    DocumentCondition,
    DocumentField,
    NotCondition,
    Operator,
)
from src.compliance.rule_kinds import (
    RULE_KINDS,
    ConditionParameters,
    DocumentAgeParameters,
    MissingDocumentParameters,
    MissingFieldParameters,
    RecordCompletenessParameters,
    RevisionWithoutReplacementParameters,
    RuleParameters,
)
from src.models import ComplianceRule, ComplianceRuleVersion, DocumentType, KeyAttribute, User
from src.models.audit import SignatureMeaning
from src.models.compliance import AttributeValueType, FindingSeverity, RuleKind, RuleLevel, StatusValue

# "COMPLIANCE_BULLETIN_AGE": capitals, digits, underscores.
RULE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
# Deep enough for any real policy; anything deeper can't be checked by a person before signing.
MAX_CONDITION_DEPTH = 5
TEXT_MATCHING = {Operator.STATED, Operator.EQUALS, Operator.ONE_OF, Operator.CONTAINS}
OPERATORS_BY_VALUE_TYPE = {
    AttributeValueType.TEXT: TEXT_MATCHING,
    AttributeValueType.TEXT_LIST: TEXT_MATCHING,
    AttributeValueType.STATUS: {Operator.STATED, Operator.EQUALS, Operator.ONE_OF},
    AttributeValueType.NUMBER: {Operator.STATED, Operator.EQUALS, Operator.ONE_OF} | NUMBER_OPERATORS,
    AttributeValueType.DATE: DATE_OPERATORS,
    AttributeValueType.RECORDS: {Operator.STATED},  # without record_field: "has any rows"
}


class RuleError(ValueError):
    """A rule that can't be saved; the message says why, for the person editing it."""


def check_attribute_condition(condition: AttributeCondition, attributes: dict[str, KeyAttribute]) -> None:
    attribute = attributes.get(condition.attribute)
    if attribute is None or not attribute.active:
        raise RuleError(f"Unknown key attribute: {condition.attribute}.")
    if condition.record_field:
        if condition.record_field not in attribute.record_fields:
            raise RuleError(f"'{condition.attribute}' records have no field: {condition.record_field}.")
        return  # a cell is text, read as whatever the operator needs
    if condition.operator not in OPERATORS_BY_VALUE_TYPE[attribute.value_type]:
        raise RuleError(
            f"'{condition.attribute}' holds {attribute.value_type.value}, which can't be compared with "
            f"{condition.operator.value}."
        )
    if attribute.value_type == AttributeValueType.STATUS and condition.operator != Operator.STATED:
        options = condition.value if isinstance(condition.value, list) else [condition.value]
        if not set(options) <= set(StatusValue):
            raise RuleError(f"'{condition.attribute}' can only be {', '.join(StatusValue)}.")


def check_document_field(
    wanted: DocumentField, needs_date: bool, type_ids: dict[str, uuid.UUID], attributes: dict[str, KeyAttribute]
) -> None:
    """A field that can't hold a value would leave its rule silently waiting forever."""
    if wanted.document_type not in type_ids:
        raise RuleError(f"Unknown document type: {wanted.document_type}.")
    if wanted.date_type is not None:
        return
    attribute = attributes.get(wanted.attribute)
    if attribute is None or not attribute.active:
        raise RuleError(f"Unknown key attribute: {wanted.attribute}.")
    if attribute.document_type_id not in (None, type_ids[wanted.document_type]):
        raise RuleError(f"'{wanted.attribute}' is not extracted from {wanted.document_type} documents.")
    if attribute.value_type == AttributeValueType.RECORDS:
        if wanted.record_field not in attribute.record_fields:
            raise RuleError(f"'{wanted.attribute}' records have no field: {wanted.record_field}.")
    elif wanted.record_field is not None:
        raise RuleError(f"'{wanted.attribute}' has no records, so it has no field {wanted.record_field}.")
    elif attribute.value_type == AttributeValueType.STATUS:
        raise RuleError(f"'{wanted.attribute}' is a yes/no status, which can't be compared between documents.")
    elif needs_date and attribute.value_type != AttributeValueType.DATE:
        raise RuleError(f"'{wanted.attribute}' is not a date.")


def check_condition_tree(
    condition: Any,
    level: RuleLevel,
    type_ids: dict[str, uuid.UUID],
    attributes: dict[str, KeyAttribute],
    depth: int = 1,
) -> None:
    """Every name must exist, and each condition must make sense at its level.

    A document has attributes and dates. A component or vendor has documents,
    so what it asks about them goes inside a document condition's `where`.
    """
    if depth > MAX_CONDITION_DEPTH:
        raise RuleError(f"Conditions may be nested at most {MAX_CONDITION_DEPTH} deep.")
    if isinstance(condition, AllOf | AnyOf):
        for child in condition.conditions:
            check_condition_tree(child, level, type_ids, attributes, depth + 1)
    elif isinstance(condition, NotCondition):
        check_condition_tree(condition.condition, level, type_ids, attributes, depth + 1)
    elif isinstance(condition, DocumentCondition):
        if level == RuleLevel.DOCUMENT:
            raise RuleError("A document rule can't require another document: make it a component or vendor rule.")
        if condition.document_type is not None and condition.document_type not in type_ids:
            raise RuleError(f"Unknown document type: {condition.document_type}.")
        if condition.where is not None:
            check_condition_tree(condition.where, RuleLevel.DOCUMENT, type_ids, attributes, depth + 1)
    elif isinstance(condition, DocumentComparison):
        if level == RuleLevel.DOCUMENT:
            raise RuleError("Comparing documents needs a component or vendor rule, which sees all its documents.")
        for side in (condition.left, condition.right):
            check_document_field(side, condition.relation == "not_after", type_ids, attributes)
    elif level != RuleLevel.DOCUMENT:
        raise RuleError(f"A {level.value} rule checks attributes and dates through a document condition's 'where'.")
    elif isinstance(condition, AttributeCondition):
        check_attribute_condition(condition, attributes)
    elif isinstance(condition, DateCondition) and condition.operator not in DATE_OPERATORS:
        raise RuleError(f"A date can't be compared with {condition.operator.value}.")


def check_references(session: Session, parameters: RuleParameters, level: RuleLevel) -> None:
    """Names in the parameters must exist: a rule about a type nobody has would never fire."""
    type_ids = dict(session.execute(select(DocumentType.name, DocumentType.id)).all())
    type_names = set(type_ids)
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
    if isinstance(parameters, DocumentAgeParameters):
        for name in parameters.governing_attributes:
            attribute = attributes.get(name)
            if attribute is None or attribute.value_type != AttributeValueType.DATE:
                raise RuleError(f"'{name}' is not a key attribute holding a date.")
    if isinstance(parameters, ConditionParameters):
        for condition in (parameters.when, parameters.require):
            if condition is not None:
                check_condition_tree(condition, level, type_ids, attributes)


def validated_parameters(
    session: Session, kind: RuleKind, level: RuleLevel, parameters: dict[str, Any]
) -> dict[str, Any]:
    """Parameters checked against the kind's model, with defaults filled in, ready to store."""
    try:
        model = RULE_KINDS[kind].parameters.model_validate(parameters)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'parameters'}: {e['msg']}" for e in error.errors())
        raise RuleError(f"Invalid parameters for {kind}: {problems}") from error
    check_references(session, model, level)
    # Storing the full model (defaults included) means a later change of a
    # default in code never silently changes what an existing version meant.
    return model.model_dump(mode="json")


def create_rule(
    session: Session,
    *,
    signer: User,
    code: str,
    kind: RuleKind,
    level: RuleLevel | None,
    document_type: str | None,
    name: str,
    parameters: dict[str, Any],
    severity: FindingSeverity,
    active: bool,
    change_reason: str,
    source_text: str | None = None,
) -> ComplianceRule:
    if not RULE_CODE.match(code):
        raise RuleError("Code must be 3-64 capitals, digits or underscores, starting with a letter.")
    if session.scalar(select(ComplianceRule.id).where(ComplianceRule.code == code)):
        raise RuleError(f"A rule with code {code} already exists.")
    levels = RULE_KINDS[kind].levels
    level = level or levels[0]
    if level not in levels:
        raise RuleError(f"{kind} can only be a {' or '.join(levels)} rule.")
    document_type_id = None
    if document_type is not None:
        if level != RuleLevel.DOCUMENT:
            raise RuleError(f"A {level.value} rule is about the whole {level.value}, so it can't be limited to one document type.")
        document_type_id = session.scalar(select(DocumentType.id).where(DocumentType.name == document_type))
        if document_type_id is None:
            raise RuleError(f"Unknown document type: {document_type}.")

    # Ids are set here, not by the database, because the signature's
    # fingerprint covers the version's rule_id and must be taken before saving.
    rule = ComplianceRule(id=uuid.uuid4(), code=code, kind=kind, level=level, document_type_id=document_type_id)
    version = ComplianceRuleVersion(
        rule_id=rule.id,
        version=1,
        name=name,
        parameters=validated_parameters(session, kind, level, parameters),
        severity=severity,
        active=active,
        source_text=source_text,
        change_reason=change_reason,
        changed_by_id=signer.id,
    )
    sign(session, signer, SignatureMeaning.APPROVAL, version, change_reason)
    rule.versions.append(version)
    session.add(rule)
    session.flush()
    return rule


def update_rule(
    session: Session,
    rule: ComplianceRule,
    *,
    signer: User,
    name: str,
    parameters: dict[str, Any],
    severity: FindingSeverity,
    active: bool,
    change_reason: str,
) -> ComplianceRuleVersion:
    """Add the next version. The rule's code, kind, level and document type never change:
    a rule about something else is a new rule, so old findings keep their meaning."""
    version = ComplianceRuleVersion(
        rule_id=rule.id,
        version=rule.current.version + 1,
        name=name,
        parameters=validated_parameters(session, rule.kind, rule.level, parameters),
        severity=severity,
        active=active,
        change_reason=change_reason,
        changed_by_id=signer.id,
    )
    sign(session, signer, SignatureMeaning.APPROVAL, version, change_reason)
    rule.versions.append(version)
    session.flush()
    return version
