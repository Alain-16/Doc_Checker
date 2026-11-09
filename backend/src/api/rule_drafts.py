import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from openai import OpenAIError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.auth.dependencies import POLICY_EDITORS, confirm_signature_or_401, require_role
from src.compliance.drafting import clarify_draft, confirm_draft, create_draft
from src.compliance.rules import RuleError
from src.config.database import get_session
from src.models import RuleDraft, User
from src.models.compliance import RuleDraftStatus
from src.workers.celery_app import EVALUATE_ALL_COMPLIANCE_TASK, FILL_IN_ATTRIBUTES_TASK, celery_app

logger = logging.getLogger(__name__)

# Drafting costs an LLM call and a draft can become a rule, so only those who change rules use it.
router = APIRouter(prefix="/rule-drafts", tags=["rule drafts"])
MAX_POLICY_CHARACTERS = 20_000


class DraftRequest(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_POLICY_CHARACTERS, description="The policy, in QA's own words.")


class ClarifyRequest(BaseModel):
    answers: str = Field(min_length=2, max_length=MAX_POLICY_CHARACTERS, description="Answers to the draft's questions.")


class ConfirmRequest(BaseModel):
    items: list[int] | None = Field(default=None, description="Item positions to sign; empty = every ready item.")
    change_reason: str = Field(min_length=10, description="Why these rules are added (audit trail).")
    password: str = Field(min_length=1, description="Your password, to sign the rules.")


class DraftOut(BaseModel):
    id: uuid.UUID
    status: RuleDraftStatus
    source_text: str
    # Per rule: quote, name, status (ready, needs_clarification, invalid), questions,
    # problems, warnings, read_back, preview, documents_to_read, what it would create.
    items: list[dict[str, Any]]
    created_at: datetime


class ConfirmOut(BaseModel):
    draft: DraftOut
    rule_codes: list[str]
    reading_documents: bool  # True while old documents are read for the new attributes


def draft_out(draft: RuleDraft) -> DraftOut:
    return DraftOut.model_validate(draft, from_attributes=True)


def get_draft(session: Session, draft_id: uuid.UUID) -> RuleDraft:
    draft = session.get(RuleDraft, draft_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found.")
    return draft


def drafting(make_draft: Callable[[], RuleDraft]) -> RuleDraft:
    """The LLM being unavailable is a temporary state, not a bug: say so."""
    try:
        return make_draft()
    except OpenAIError as error:
        logger.exception("Drafting rules failed.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Drafting is unavailable; try again shortly.") from error


@router.post("", response_model=DraftOut, status_code=status.HTTP_201_CREATED)
def draft_rules(
    body: DraftRequest, user: User = Depends(require_role(*POLICY_EDITORS)), session: Session = Depends(get_session)
) -> DraftOut:
    """Turn a written policy into proposed rules. Nothing takes effect until confirmed."""
    draft = drafting(lambda: create_draft(session, body.text, user))
    session.commit()
    return draft_out(draft)


@router.get("/{draft_id}", response_model=DraftOut, dependencies=[Depends(require_role(*POLICY_EDITORS))])
def read_draft(draft_id: uuid.UUID, session: Session = Depends(get_session)) -> DraftOut:
    return draft_out(get_draft(session, draft_id))


@router.post("/{draft_id}/clarify", response_model=DraftOut, status_code=status.HTTP_201_CREATED)
def clarify(
    draft_id: uuid.UUID,
    body: ClarifyRequest,
    user: User = Depends(require_role(*POLICY_EDITORS)),
    session: Session = Depends(get_session),
) -> DraftOut:
    """Answer a draft's questions: gives a new draft to review."""
    original = get_draft(session, draft_id)
    draft = drafting(lambda: clarify_draft(session, original, body.answers, user))
    session.commit()
    return draft_out(draft)


@router.post("/{draft_id}/confirm", response_model=ConfirmOut)
def confirm(
    draft_id: uuid.UUID,
    body: ConfirmRequest,
    user: User = Depends(require_role(*POLICY_EDITORS)),
    session: Session = Depends(get_session),
) -> ConfirmOut:
    """Sign the draft's rules into force, then read old documents for any new attribute and re-judge."""
    draft = get_draft(session, draft_id)
    confirm_signature_or_401(session, user, body.password)
    try:
        rules, attribute_ids = confirm_draft(session, draft, user, body.items, body.change_reason)
    except RuleError as error:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    codes = [rule.code for rule in rules]
    session.commit()
    if attribute_ids:
        # Ends by re-judging everything, so one job does both.
        celery_app.send_task(FILL_IN_ATTRIBUTES_TASK, args=[[str(i) for i in attribute_ids]])
    else:
        celery_app.send_task(EVALUATE_ALL_COMPLIANCE_TASK)
    return ConfirmOut(draft=draft_out(draft), rule_codes=codes, reading_documents=bool(attribute_ids))
