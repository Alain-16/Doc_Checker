from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.orm import Session

from src.auth.accounts import AccountError, accept_invite, request_password_reset, reset_password
from src.auth.dependencies import current_user, signing_in_session
from src.auth.login import SignInError, sign_in, start_mfa_setup, verify_mfa_code
from src.auth.passwords import PasswordRuleError
from src.auth.session import SESSION_COOKIE, end_session
from src.config.database import get_session
from src.config.settings import get_settings
from src.models import User, UserSession
from src.models.user import SessionEndReason, UserRole

# Public on purpose: these are the endpoints you use BEFORE you are signed in.
router = APIRouter(prefix="/auth", tags=["auth"])


# --- Shapes ---


class SignInRequest(BaseModel):
    # Plain text, not EmailStr: sign-in only looks the address up; checking its
    # format would just answer differently for malformed input.
    email: str
    password: str


class SignInStep(BaseModel):
    # What the client must do next: "setup" = scan a QR code first; "code" = enter the app's code.
    mfa: str


class MfaSetupOut(BaseModel):
    otpauth_uri: str  # show as a QR code


class CodeRequest(BaseModel):
    code: str


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str
    full_name: str
    role: UserRole


class NewPassword(BaseModel):
    token: str
    password: str


class ResetRequest(BaseModel):
    email: EmailStr


# --- Signing in ---


def sign_in_failure(session: Session, error: SignInError) -> HTTPException:
    # Commit first: the failed-attempt count and any lock must be saved even though we refuse.
    session.commit()
    code = status.HTTP_423_LOCKED if error.locked else status.HTTP_401_UNAUTHORIZED
    return HTTPException(code, str(error))


@router.post("/login", response_model=SignInStep)
def login(body: SignInRequest, response: Response, session: Session = Depends(get_session)) -> SignInStep:
    """Step 1 of 2: email and password. Sets the session cookie; the session works only after step 2."""
    try:
        user, token = sign_in(session, body.email, body.password, datetime.now(UTC))
    except SignInError as error:
        raise sign_in_failure(session, error) from error
    session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,  # page scripts can't read it, so injected JavaScript can't steal it
        samesite="lax",  # not sent with requests started by other websites' forms
        secure=get_settings().app_env != "local",  # HTTPS only, except on your own machine
    )
    return SignInStep(mfa="code" if user.mfa_enabled_at else "setup")


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(user_session: UserSession = Depends(signing_in_session), session: Session = Depends(get_session)) -> MfaSetupOut:
    """First sign-in only: a new authenticator secret. Refused once MFA is on (an Admin resets it)."""
    if user_session.user.mfa_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The authenticator app is already set up.")
    uri = start_mfa_setup(session, user_session.user)
    session.commit()
    return MfaSetupOut(otpauth_uri=uri)


@router.post("/mfa/verify", response_model=MeOut)
def mfa_verify(
    body: CodeRequest, user_session: UserSession = Depends(signing_in_session), session: Session = Depends(get_session)
) -> User:
    """Step 2 of 2: the 6-digit code from the app. After this the session is fully signed in."""
    try:
        user = verify_mfa_code(session, user_session, body.code, datetime.now(UTC))
    except SignInError as error:
        raise sign_in_failure(session, error) from error
    session.commit()
    return user


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response, user_session: UserSession = Depends(signing_in_session), session: Session = Depends(get_session)
) -> None:
    end_session(user_session, SessionEndReason.LOGOUT, datetime.now(UTC))
    session.commit()
    response.delete_cookie(SESSION_COOKIE)


# --- Emailed links ---


def account_failure(error: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


@router.post("/invitations/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_invitation(body: NewPassword, session: Session = Depends(get_session)) -> None:
    try:
        accept_invite(session, body.token, body.password, datetime.now(UTC))
    except (AccountError, PasswordRuleError) as error:
        raise account_failure(error) from error
    session.commit()


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def password_reset_request(body: ResetRequest, session: Session = Depends(get_session)) -> None:
    """Always 202, whether or not the email has an account."""
    request_password_reset(session, body.email, datetime.now(UTC))
    session.commit()


@router.post("/password-reset/complete", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_complete(body: NewPassword, session: Session = Depends(get_session)) -> None:
    try:
        reset_password(session, body.token, body.password, datetime.now(UTC))
    except (AccountError, PasswordRuleError) as error:
        raise account_failure(error) from error
    session.commit()