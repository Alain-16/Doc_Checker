from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit.trail import set_actor, set_audit_reason
from src.auth.mfa import code_is_valid, decrypt_secret, encrypt_secret, new_secret, setup_link
from src.auth.passwords import password_matches
from src.auth.session import end_all_sessions, start_session
from src.config.settings import get_settings
from src.models import User, UserSession
from src.models.user import SessionEndReason


class SignInError(Exception):
    """Sign-in refused. `locked` tells the API to answer 423 (locked) instead of 401."""

    def __init__(self, message: str, locked: bool = False) -> None:
        super().__init__(message)
        self.locked = locked


# One message for every wrong-credentials case, so it doesn't reveal which emails exist.
INVALID_CREDENTIALS = "Invalid email or password."
ACCOUNT_LOCKED = "This account is locked after repeated failed attempts. Ask an Admin to unlock it."


def register_failed_attempt(session: Session, user: User, now: datetime) -> None:
    """Count a wrong password or code; lock the account at the limit (PRD: 5)."""
    user.failed_login_count += 1
    if user.failed_login_count >= get_settings().max_failed_logins and user.locked_at is None:
        user.locked_at = now
        end_all_sessions(session, user, SessionEndReason.REVOKED, now)
        set_audit_reason(session, f"Locked after {user.failed_login_count} failed attempts.")


def check_password(session: Session, email: str, password: str, now: datetime) -> User:
    """Step 1: the user whose password this is, or SignInError. Counts failures."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        password_matches(None, password)  # same time as a real check
        raise SignInError(INVALID_CREDENTIALS)
    if user.locked_at is not None:
        raise SignInError(ACCOUNT_LOCKED, locked=True)
    if not password_matches(user.password_hash, password):
        register_failed_attempt(session, user, now)
        raise SignInError(ACCOUNT_LOCKED if user.locked_at else INVALID_CREDENTIALS, locked=user.locked_at is not None)
    user.failed_login_count = 0
    return user


def sign_in(session: Session, email: str, password: str, now: datetime) -> tuple[User, str]:
    """Password step: opens a session that can only finish signing in (MFA still pending)."""
    user = check_password(session, email, password, now)
    return user, start_session(session, user, now)


def start_mfa_setup(session: Session, user: User) -> str:
    """First sign-in: a new secret, stored encrypted; returns the link to show as a QR code.

    Not active until a correct code proves the app has it (verify_mfa_code).
    Calling it again replaces the secret, e.g. if the first QR code was lost.
    """
    secret = new_secret()
    set_actor(session, user)
    set_audit_reason(session, "Authenticator app setup started.")
    user.mfa_secret_encrypted = encrypt_secret(secret)
    return setup_link(user.email, secret)


def verify_mfa_code(session: Session, user_session: UserSession, code: str, now: datetime) -> User:
    """Code step: completes sign-in. The first correct code also switches MFA on."""
    user = user_session.user
    if user.mfa_secret_encrypted is None:
        raise SignInError("Set up the authenticator app first.")
    if not code_is_valid(decrypt_secret(user.mfa_secret_encrypted), code):
        register_failed_attempt(session, user, now)
        raise SignInError(ACCOUNT_LOCKED if user.locked_at else "Invalid code.", locked=user.locked_at is not None)
    if user.mfa_enabled_at is None:
        set_actor(session, user)
        set_audit_reason(session, "Authenticator app setup completed.")
        user.mfa_enabled_at = now
    user.failed_login_count = 0
    user.last_login_at = now
    user_session.mfa_verified_at = now
    return user