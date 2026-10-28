from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.audit.trail import set_audit_reason
from src.auth.passwords import check_password_rules, hash_password
from src.auth.session import end_all_sessions
from src.auth.tokens import new_token, token_hash
from src.config.settings import get_settings
from src.models import AccountToken, User
from src.models.user import SessionEndReason, TokenPurpose, UserRole
from src.auth.email import send_email

INVITE_VALID_FOR = timedelta(days=3)
RESET_VALID_FOR = timedelta(hours=1)


class AccountError(ValueError):
    """An account action that can't be done; the message is safe to show."""


def issue_token(session: Session, user: User, purpose: TokenPurpose, valid_for: timedelta, now: datetime) -> str:
    token, stored_hash = new_token()
    session.add(AccountToken(user_id=user.id, purpose=purpose, token_hash=stored_hash, expires_at=now + valid_for))
    return token


def use_token(session: Session, token: str, purpose: TokenPurpose, now: datetime) -> User:
    """The user a valid, unused, unexpired token belongs to; marks the token used."""
    row = session.scalar(
        select(AccountToken).where(AccountToken.token_hash == token_hash(token), AccountToken.purpose == purpose)
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise AccountError("This link is invalid, already used, or expired.")
    row.used_at = now
    return row.user


def link(path: str, token: str) -> str:
    return f"{str(get_settings().app_base_url).rstrip('/')}/{path}?token={token}"


def invite_user(session: Session, admin: User, email: str, full_name: str, role: UserRole, now: datetime) -> User:
    """Create the account (no password yet) and email a single-use link to choose one."""
    email = email.strip().lower()
    if session.scalar(select(User.id).where(User.email == email)):
        raise AccountError(f"An account for {email} already exists.")
    user = User(email=email, full_name=full_name.strip(), role=role, invited_by_id=admin.id)
    session.add(user)
    session.flush()  # user.id is needed by the token
    token = issue_token(session, user, TokenPurpose.INVITE, INVITE_VALID_FOR, now)
    send_email(
        email,
        "You're invited to Doc Checker",
        f"{admin.full_name} invited you as {role.value.replace('_', ' ')}.\n"
        f"Choose your password here (valid {INVITE_VALID_FOR.days} days):\n{link('accept-invite', token)}\n"
        "You'll then set up an authenticator app at your first sign-in.",
    )
    return user


def accept_invite(session: Session, token: str, password: str, now: datetime) -> User:
    check_password_rules(password)
    user = use_token(session, token, TokenPurpose.INVITE, now)
    # Not signed in yet, so recorded as a system change, with the reason.
    set_audit_reason(session, "Invitation accepted; password set by the user.")
    user.password_hash = hash_password(password)
    return user


def request_password_reset(session: Session, email: str, now: datetime) -> None:
    """Email a reset link if the account exists. The caller answers the same either way,
    so this can't be used to find out which emails have accounts."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or user.password_hash is None:
        return
    token = issue_token(session, user, TokenPurpose.PASSWORD_RESET, RESET_VALID_FOR, now)
    send_email(
        user.email,
        "Reset your Doc Checker password",
        f"Choose a new password here (valid {int(RESET_VALID_FOR.total_seconds() // 60)} minutes):\n"
        f"{link('reset-password', token)}\nIf you didn't ask for this, ignore this email.",
    )


def reset_password(session: Session, token: str, password: str, now: datetime) -> User:
    """Set the new password and sign the user out everywhere. A lock stays: only an Admin unlocks."""
    check_password_rules(password)
    user = use_token(session, token, TokenPurpose.PASSWORD_RESET, now)
    set_audit_reason(session, "Password reset through an emailed link.")
    user.password_hash = hash_password(password)
    end_all_sessions(session, user, SessionEndReason.REVOKED, now)
    return user


def ensure_default_admin(session: Session) -> str | None:
    """Make sure the system always has an Admin who can sign in. Called at API start-up.

    "Usable" = active and not locked. If none exists, the Admin named in the
    settings is created, or, if that account already exists, unlocked and
    reactivated: the recovery path when the last Admin locked themselves out.
    Returns what was done (for the log), or None when an Admin was already there.
    """
    usable_admin = session.scalar(
        select(User.id).where(User.role == UserRole.ADMIN, User.is_active, User.locked_at.is_(None))
    )
    if usable_admin is not None:
        return None

    settings = get_settings()
    if not settings.default_admin_email:
        raise AccountError(
            "No active, unlocked Admin exists: set DEFAULT_ADMIN_EMAIL (and, for a new account, "
            "DEFAULT_ADMIN_NAME and DEFAULT_ADMIN_PASSWORD) so one can be created."
        )
    email = settings.default_admin_email.strip().lower()
    existing = session.scalar(select(User).where(User.email == email))

    if existing is not None:
        # Never turn someone else's account into an Admin from a settings file.
        if existing.role != UserRole.ADMIN:
            raise AccountError(f"DEFAULT_ADMIN_EMAIL {email} belongs to a {existing.role.value}, not an Admin.")
        set_audit_reason(session, "Start-up recovery: no usable Admin existed; default Admin unlocked and reactivated.")
        existing.locked_at = None
        existing.failed_login_count = 0
        existing.is_active = True
        return f"Default Admin {email} unlocked and reactivated."

    if not settings.default_admin_name or settings.default_admin_password is None:
        raise AccountError("DEFAULT_ADMIN_NAME and DEFAULT_ADMIN_PASSWORD are needed to create the default Admin.")
    password = settings.default_admin_password.get_secret_value()
    check_password_rules(password)
    set_audit_reason(session, "Start-up: no usable Admin existed; default Admin created from settings.")
    session.add(
        User(email=email, full_name=settings.default_admin_name.strip(), role=UserRole.ADMIN, password_hash=hash_password(password))
    )
    return f"Default Admin {email} created. Sign in to set up the authenticator app."