from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.auth.tokens import new_token, token_hash
from src.config.settings import get_settings
from src.models import User, UserSession
from src.models.user import SessionEndReason

SESSION_COOKIE = "session"


def start_session(session: Session, user: User, now: datetime) -> str:
    """Open a session for the user and return the token for the cookie (shown once, never stored)."""
    token, stored_hash = new_token()
    session.add(UserSession(user_id=user.id, token_hash=stored_hash, last_seen_at=now))
    return token


def end_session(user_session: UserSession, reason: SessionEndReason, now: datetime) -> None:
    user_session.ended_at = now
    user_session.end_reason = reason


def end_all_sessions(session: Session, user: User, reason: SessionEndReason, now: datetime) -> None:
    """Sign the user out everywhere (password reset, deactivation, lock)."""
    session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.ended_at.is_(None))
        .values(ended_at=now, end_reason=reason)
    )


def find_session(session: Session, token: str | None, now: datetime) -> UserSession | None:
    """The live session for this cookie token, or None.

    A session idle for longer than the limit is ended here, on its next use:
    no background job is needed to expire sessions.
    """
    if not token:
        return None
    user_session = session.scalar(
        select(UserSession).where(UserSession.token_hash == token_hash(token), UserSession.ended_at.is_(None))
    )
    if user_session is None:
        return None
    if now - user_session.last_seen_at > timedelta(minutes=get_settings().session_idle_minutes):
        end_session(user_session, SessionEndReason.IDLE, now)
        return None
    user_session.last_seen_at = now
    return user_session