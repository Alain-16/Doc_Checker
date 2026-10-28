import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit.trail import set_audit_reason
from src.auth.accounts import AccountError, invite_user
from src.auth.dependencies import ADMINS, require_role
from src.auth.session import end_all_sessions
from src.config.database import get_session
from src.models import User
from src.models.user import SessionEndReason, UserRole

# Every endpoint here is Admin-only (PRD: user management).
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_role(*ADMINS))])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    invite_accepted: bool
    mfa_enabled: bool
    locked_at: datetime | None
    last_login_at: datetime | None


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role, is_active=user.is_active,
        invite_accepted=user.password_hash is not None, mfa_enabled=user.mfa_enabled_at is not None,
        locked_at=user.locked_at, last_login_at=user.last_login_at,
    )


class Invitation(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1)
    role: UserRole


class Reason(BaseModel):
    reason: str = Field(min_length=10, description="Why (audit trail).")


class RoleChange(Reason):
    role: UserRole


def get_user(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return user


def not_yourself(admin: User, user: User, action: str) -> None:
    # Stops an Admin from locking everyone, themselves included, out of administration.
    if admin.id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"You can't {action} your own account.")


@router.get("", response_model=list[UserOut])
def list_users(session: Session = Depends(get_session)) -> list[UserOut]:
    return [user_out(user) for user in session.scalars(select(User).order_by(User.full_name))]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def invite(body: Invitation, admin: User = Depends(require_role(*ADMINS)), session: Session = Depends(get_session)) -> UserOut:
    """Create the account and email the invitation link (no public sign-up)."""
    try:
        user = invite_user(session, admin, body.email, body.full_name, body.role, datetime.now(UTC))
    except AccountError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    session.commit()
    return user_out(user)


@router.put("/{user_id}/role", response_model=UserOut)
def change_role(
    user_id: uuid.UUID, body: RoleChange, admin: User = Depends(require_role(*ADMINS)), session: Session = Depends(get_session)
) -> UserOut:
    user = get_user(session, user_id)
    not_yourself(admin, user, "change the role of")
    set_audit_reason(session, body.reason)
    user.role = body.role
    session.commit()
    return user_out(user)


@router.post("/{user_id}/unlock", response_model=UserOut)
def unlock(
    user_id: uuid.UUID, body: Reason, session: Session = Depends(get_session)
) -> UserOut:
    user = get_user(session, user_id)
    set_audit_reason(session, body.reason)
    user.locked_at = None
    user.failed_login_count = 0
    session.commit()
    return user_out(user)


@router.post("/{user_id}/deactivate", response_model=UserOut)
def deactivate(
    user_id: uuid.UUID, body: Reason, admin: User = Depends(require_role(*ADMINS)), session: Session = Depends(get_session)
) -> UserOut:
    """Accounts are never deleted (their signatures and audit entries must keep a real
    person); deactivating signs them out everywhere and blocks sign-in."""
    user = get_user(session, user_id)
    not_yourself(admin, user, "deactivate")
    set_audit_reason(session, body.reason)
    user.is_active = False
    end_all_sessions(session, user, SessionEndReason.REVOKED, datetime.now(UTC))
    session.commit()
    return user_out(user)