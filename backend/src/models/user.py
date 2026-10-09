import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, text, true
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, enum_check, string_enum


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