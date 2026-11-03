import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.audit.trail import set_audit_reason
from src.auth.dependencies import ADMINS, require_role
from src.config.database import get_session
from src.models import Component, OwnerAssignment, User, Vendor

# Admins decide who is responsible for what (PRD: Admins manage vendors and components).
router = APIRouter(prefix="/owners", tags=["owners"], dependencies=[Depends(require_role(*ADMINS))])


class OwnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    vendor_id: uuid.UUID | None
    component_id: uuid.UUID | None
    created_at: datetime


class OwnerCreate(BaseModel):
    user_id: uuid.UUID
    vendor_id: uuid.UUID | None = None
    component_id: uuid.UUID | None = None
    reason: str = Field(min_length=10, description="Why this person is responsible (audit trail).")

    @model_validator(mode="after")
    def exactly_one_subject(self) -> "OwnerCreate":
        if (self.vendor_id is None) == (self.component_id is None):
            raise ValueError("Give either vendor_id or component_id, not both or neither.")
        return self


class Removal(BaseModel):
    reason: str = Field(min_length=10, description="Why the assignment ends (audit trail).")


def owner_out(assignment: OwnerAssignment) -> OwnerOut:
    return OwnerOut(
        id=assignment.id, user_id=assignment.user_id, user_name=assignment.user.full_name,
        vendor_id=assignment.vendor_id, component_id=assignment.component_id, created_at=assignment.created_at,
    )


@router.get("", response_model=list[OwnerOut])
def list_owners(
    vendor_id: uuid.UUID | None = None, component_id: uuid.UUID | None = None, session: Session = Depends(get_session)
) -> list[OwnerOut]:
    query = select(OwnerAssignment).options(selectinload(OwnerAssignment.user))
    if vendor_id:
        query = query.where(OwnerAssignment.vendor_id == vendor_id)
    if component_id:
        query = query.where(OwnerAssignment.component_id == component_id)
    return [owner_out(assignment) for assignment in session.scalars(query.order_by(OwnerAssignment.created_at))]


@router.post("", response_model=OwnerOut, status_code=status.HTTP_201_CREATED)
def assign_owner(body: OwnerCreate, session: Session = Depends(get_session)) -> OwnerOut:
    user = session.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown or inactive user.")
    if body.vendor_id and session.get(Vendor, body.vendor_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown vendor.")
    if body.component_id and session.get(Component, body.component_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown component.")
    set_audit_reason(session, body.reason)
    assignment = OwnerAssignment(user_id=user.id, vendor_id=body.vendor_id, component_id=body.component_id)
    session.add(assignment)
    try:
        session.commit()
    except IntegrityError as error:  # the partial unique index: already assigned
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This person is already an owner of it.") from error
    return owner_out(assignment)


@router.post("/{assignment_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
def remove_owner(assignment_id: uuid.UUID, body: Removal, session: Session = Depends(get_session)) -> None:
    """POST with a reason, not DELETE: a removal must say why, and DELETE requests carry no body."""
    assignment = session.get(OwnerAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found.")
    set_audit_reason(session, body.reason)
    session.delete(assignment)
    session.commit()
