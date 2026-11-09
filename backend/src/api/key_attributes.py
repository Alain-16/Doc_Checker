import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit.trail import set_audit_reason
from src.auth.dependencies import POLICY_EDITORS, current_user, require_role
from src.compliance.attributes import AttributeSpec, add_key_attribute
from src.compliance.rules import RuleError
from src.config.database import get_session
from src.models import DocumentType, KeyAttribute
from src.models.compliance import AttributeGroup, AttributeValueType
from src.workers.celery_app import FILL_IN_ATTRIBUTES_TASK, celery_app

# Everyone signed in can read the list; Compliance Specialists and Admins change it.
router = APIRouter(prefix="/key-attributes", tags=["key attributes"], dependencies=[Depends(current_user)])


class AttributeOut(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: str
    attribute_group: AttributeGroup
    value_type: AttributeValueType
    document_type: str | None  # None = every document type
    record_fields: list[str]
    search_query: str | None
    required: bool
    active: bool


class AttributeCreate(BaseModel):
    name: str = Field(examples=["liability_cover"])
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=5, description="What to look for; the unit for a number.")
    value_type: AttributeValueType
    search_query: str = Field(min_length=3, description="The passage to look for in each document.")
    document_type: str | None = Field(default=None, description="Document type name; empty = every type.")
    record_fields: list[str] = Field(default_factory=list)
    required: bool = False
    reason: str = Field(min_length=10, description="Why it is added (audit trail).")


class AttributeChange(BaseModel):
    """Name, value type and record fields never change: stored values and rules rely on them."""

    display_name: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=5)
    search_query: str | None = Field(default=None, min_length=3)
    required: bool | None = None
    active: bool | None = None
    reason: str = Field(min_length=10, description="Why it changes (audit trail).")


def attribute_out(attribute: KeyAttribute, session: Session) -> AttributeOut:
    fields = {name: getattr(attribute, name) for name in AttributeOut.model_fields if name != "document_type"}
    type_name = session.get(DocumentType, attribute.document_type_id).name if attribute.document_type_id else None
    return AttributeOut(**fields, document_type=type_name)


def get_attribute(session: Session, attribute_id: uuid.UUID) -> KeyAttribute:
    attribute = session.get(KeyAttribute, attribute_id)
    if attribute is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key attribute not found.")
    return attribute


def fill_in(attribute: KeyAttribute) -> None:
    celery_app.send_task(FILL_IN_ATTRIBUTES_TASK, args=[[str(attribute.id)]])


@router.get("", response_model=list[AttributeOut])
def list_attributes(active_only: bool = False, session: Session = Depends(get_session)) -> list[AttributeOut]:
    attributes = session.scalars(select(KeyAttribute).order_by(KeyAttribute.name)).all()
    return [attribute_out(a, session) for a in attributes if a.active or not active_only]


@router.post(
    "", response_model=AttributeOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(*POLICY_EDITORS))],
)
def add_attribute(body: AttributeCreate, session: Session = Depends(get_session)) -> AttributeOut:
    """Add an attribute to extract. Documents already on file are read for it automatically."""
    set_audit_reason(session, body.reason)
    try:
        attribute = add_key_attribute(session, AttributeSpec(**body.model_dump(exclude={"reason"})))
    except RuleError as error:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    session.commit()
    fill_in(attribute)
    return attribute_out(attribute, session)


@router.put("/{attribute_id}", response_model=AttributeOut, dependencies=[Depends(require_role(*POLICY_EDITORS))])
def change_attribute(
    attribute_id: uuid.UUID, body: AttributeChange, session: Session = Depends(get_session)
) -> AttributeOut:
    """Change it for documents processed from now on; values already read stay as they are.
    Turning an attribute back on reads the documents that missed it."""
    attribute = get_attribute(session, attribute_id)
    was_active = attribute.active
    set_audit_reason(session, body.reason)
    for name, value in body.model_dump(exclude={"reason"}, exclude_none=True).items():
        setattr(attribute, name, value)
    session.commit()
    if attribute.active and not was_active:
        fill_in(attribute)
    return attribute_out(attribute, session)
