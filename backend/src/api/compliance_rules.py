import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.auth.dependencies import POLICY_EDITORS, confirm_signature_or_401, current_user, require_role
from src.compliance.rule_kinds import RULE_KINDS
from src.compliance.rules import RuleError, create_rule, update_rule
from src.config.database import get_session
from src.models import ComplianceRule, User
from src.models.compliance import FindingSeverity, RuleKind
from src.workers.celery_app import EVALUATE_ALL_COMPLIANCE_TASK, celery_app

# Everyone signed in can read rules; Compliance Specialists and Admins change them, with an e-signature.
router = APIRouter(prefix="/compliance-rules", tags=["compliance rules"], dependencies=[Depends(current_user)])


# --- Request and response shapes ---


class RuleKindOut(BaseModel):
    kind: RuleKind
    level: Literal["document", "component"]
    description: str
    # JSON Schema of the kind's parameters, so a QA screen can build its form from it.
    parameters_schema: dict[str, Any]


class RuleVersionOut(BaseModel):
    version: int
    name: str
    parameters: dict[str, Any]
    severity: FindingSeverity
    active: bool
    change_reason: str
    changed_by_id: uuid.UUID | None
    created_at: datetime


class RuleOut(BaseModel):
    id: uuid.UUID
    code: str
    kind: RuleKind
    level: Literal["document", "component"]
    document_type: str | None  # None = every document type
    current: RuleVersionOut


class RuleDetailOut(RuleOut):
    versions: list[RuleVersionOut]  # oldest first


class RuleSettings(BaseModel):
    """What every version sets. A PUT sends all of it: the new version is complete on its own."""

    name: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    severity: FindingSeverity
    active: bool = True
    change_reason: str = Field(min_length=10, description="Why this rule is created or changed (audit trail).")
    # The signer's password again: every change is electronically signed (Part 11 §11.200).
    password: str = Field(min_length=1, description="Your password, to sign this change.")


class RuleCreate(RuleSettings):
    code: str = Field(examples=["FORMULATION_FIVE_YEAR_AGE"])
    kind: RuleKind
    document_type: str | None = Field(default=None, description="Document type name; empty = every type.")


def version_out(version) -> RuleVersionOut:
    return RuleVersionOut.model_validate(version, from_attributes=True)


def rule_out(rule: ComplianceRule, with_history: bool = False) -> RuleOut:
    fields = dict(
        id=rule.id,
        code=rule.code,
        kind=rule.kind,
        level=RULE_KINDS[rule.kind].level,
        document_type=rule.document_type.name if rule.document_type else None,
        current=version_out(rule.current),
    )
    if with_history:
        return RuleDetailOut(**fields, versions=[version_out(v) for v in rule.versions])
    return RuleOut(**fields)


def get_rule(session: Session, rule_id: uuid.UUID) -> ComplianceRule:
    rule = session.scalar(
        select(ComplianceRule)
        .where(ComplianceRule.id == rule_id)
        .options(selectinload(ComplianceRule.versions), selectinload(ComplianceRule.document_type))
    )
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    return rule


def save_and_reevaluate(session: Session) -> None:
    session.commit()
    # Every status may change with the rules, so everything is re-judged in the background.
    celery_app.send_task(EVALUATE_ALL_COMPLIANCE_TASK)


# --- Endpoints ---


@router.get("/kinds", response_model=list[RuleKindOut])
def list_kinds() -> list[RuleKindOut]:
    """The checks rules can be made from, with their parameters."""
    return [
        RuleKindOut(kind=kind, level=spec.level, description=spec.description, parameters_schema=spec.parameters.model_json_schema())
        for kind, spec in RULE_KINDS.items()
    ]


@router.get("", response_model=list[RuleOut])
def list_rules(active_only: bool = False, session: Session = Depends(get_session)) -> list[RuleOut]:
    rules = session.scalars(
        select(ComplianceRule)
        .options(selectinload(ComplianceRule.versions), selectinload(ComplianceRule.document_type))
        .order_by(ComplianceRule.code)
    ).all()
    return [rule_out(rule) for rule in rules if rule.current.active or not active_only]


@router.get("/{rule_id}", response_model=RuleDetailOut)
def read_rule(rule_id: uuid.UUID, session: Session = Depends(get_session)) -> RuleOut:
    return rule_out(get_rule(session, rule_id), with_history=True)


@router.post("", response_model=RuleDetailOut, status_code=status.HTTP_201_CREATED)
def add_rule(
    body: RuleCreate, user: User = Depends(require_role(*POLICY_EDITORS)), session: Session = Depends(get_session)
) -> RuleOut:
    confirm_signature_or_401(session, user, body.password)
    try:
        rule = create_rule(session, signer=user, **body.model_dump(exclude={"password"}))
    except RuleError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    save_and_reevaluate(session)
    return rule_out(get_rule(session, rule.id), with_history=True)


@router.put("/{rule_id}", response_model=RuleDetailOut)
def change_rule(
    rule_id: uuid.UUID,
    body: RuleSettings,
    user: User = Depends(require_role(*POLICY_EDITORS)),
    session: Session = Depends(get_session),
) -> RuleOut:
    """Save new settings as the next, signed version. To retire a rule, send active=false."""
    rule = get_rule(session, rule_id)
    confirm_signature_or_401(session, user, body.password)
    try:
        update_rule(session, rule, signer=user, **body.model_dump(exclude={"password"}))
    except RuleError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    save_and_reevaluate(session)
    return rule_out(get_rule(session, rule.id), with_history=True)
