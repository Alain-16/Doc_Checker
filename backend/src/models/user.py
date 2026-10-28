import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, text, true
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, enum_check, string_enum
from sqlalchemy import CheckConstraint, ForeignKey, String, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship



class TokenPurpose(StrEnum):
    INVITE = "invite"
    PASSWORD_RESET = "password_reset"


class SessionEndReason(StrEnum):
    LOGOUT = "logout"
    IDLE = "idle"  # no request for longer than the idle limit
    REVOKED = "revoked"  # ended by the system: password reset, deactivation, lock


# Length of a SHA-256 hash written as hexadecimal text.
TOKEN_HASH_LENGTH = 64

class UserSession(Base):
    """One signed-in browser. The cookie holds a random token; only its hash is stored here,
    so a copy of this table can't be used to sign in."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ended_fields_together"),
        enum_check("end_reason", SessionEndReason),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    # Empty until the MFA code is checked: until then the session can only finish signing in.
    mfa_verified_at: Mapped[datetime | None]
    # Moved forward on every request; the idle timeout is measured from it.
    last_seen_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    end_reason: Mapped[SessionEndReason | None] = mapped_column(string_enum(SessionEndReason))

    user: Mapped["User"] = relationship()


class AccountToken(Base):
    """A single-use link sent by email (invite or password reset). Only the hash is stored."""

    __tablename__ = "account_tokens"
    __table_args__ = (enum_check("purpose", TokenPurpose),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(string_enum(TokenPurpose))
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]

    user: Mapped["User"] = relationship()

class UserRole(StrEnum):
    QA_ANALYST = "qa_analyst"
    COMPLIANCE_SPECIALIST = "compliance_specialist"
    ADMIN = "admin"


class User(Base):
    """A person with an account. Never deleted, only deactivated, so every
    signature and audit entry keeps pointing at a real user."""

    __tablename__ = "users"
    __table_args__ = (
        # Emails are compared lowercase, so "Ana@X.com" and "ana@x.com" can't
        # become two accounts.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_not_negative"),
        enum_check("role", UserRole),
    )

    email: Mapped[str] = mapped_column(unique=True)
    # Printed on every electronic signature this user applies (Part 11 §11.50).
    full_name: Mapped[str]
    role: Mapped[UserRole] = mapped_column(string_enum(UserRole))

    # Argon2 hash, never the password. Empty until the user accepts their invite.
    password_hash: Mapped[str | None]
    # The authenticator-app secret, encrypted before it is stored (Feature 14).
    # bytes maps to a binary column.
    mfa_secret_encrypted: Mapped[bytes | None]
    mfa_enabled_at: Mapped[datetime | None]

    # --- Lockout after repeated failed logins (Feature 14) ---
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # Set when the account locks; an Admin unlocks it by clearing this.
    locked_at: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]

    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # The Admin who sent the invite. Empty only for the very first Admin.
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )