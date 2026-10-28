from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.audit.trail import set_actor
from src.auth.session import SESSION_COOKIE, end_session, find_session
from src.config.database import get_session
from src.models import User, UserSession
from src.models.user import SessionEndReason, UserRole
from src.auth.signatures import SignatureError, confirm_signing_password

# Who may do what (PRD "Roles and Permissions", plus your decision of 2026-10-28
# that Compliance Specialists may change rules and alert policies).
EVERY_ROLE = (UserRole.QA_ANALYST, UserRole.COMPLIANCE_SPECIALIST, UserRole.ADMIN)
POLICY_EDITORS = (UserRole.COMPLIANCE_SPECIALIST, UserRole.ADMIN)
ADMINS = (UserRole.ADMIN,)

NOT_SIGNED_IN = "Not signed in, or the session ended. Sign in again."


def signing_in_session(request: Request, session: Session = Depends(get_session)) -> UserSession:
    """A live session, even one still waiting for its MFA code (only the MFA endpoints use this)."""
    now = datetime.now(UTC)
    user_session = find_session(session, request.cookies.get(SESSION_COOKIE), now)
    session.commit()  # saves last_seen_at, or the idle ending
    if user_session is None or not user_session.user.is_active or user_session.user.locked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_SIGNED_IN)
    return user_session


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """The fully signed-in user (password AND code), or 401. Everything they save is
    recorded in the audit trail under their name."""
    now = datetime.now(UTC)
    user_session = find_session(session, request.cookies.get(SESSION_COOKIE), now)
    if user_session is not None and (not user_session.user.is_active or user_session.user.locked_at is not None):
        end_session(user_session, SessionEndReason.REVOKED, now)  # deactivated or locked since signing in
        user_session = None
    session.commit()
    if user_session is None or user_session.mfa_verified_at is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_SIGNED_IN)
    set_actor(session, user_session.user)
    return user_session.user


def require_role(*roles: UserRole) -> Callable[..., User]:
    """A dependency that lets only these roles through (403 for the others)."""

    def check_role(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role isn't allowed to do this.")
        return user

    return check_role

def confirm_signature_or_401(session: Session, signer: User, password: str) -> None:
    """Endpoints that sign call this first. A wrong password is committed (it counts
    towards the lockout) and answered 401; nothing of the change is saved."""
    try:
        confirm_signing_password(session, signer, password, datetime.now(UTC))
    except SignatureError as error:
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error