import pyotp
from cryptography.fernet import Fernet

from src.config.settings import get_settings

# Shown in the authenticator app next to the account.
ISSUER_NAME = "Doc Checker"
# Accept the code of the previous and next 30-second step too, so a phone
# clock a few seconds off still works.
CLOCK_DRIFT_STEPS = 1


def fernet() -> Fernet:
    """Symmetric encryption with the key from settings. The secret must be
    readable again to check codes, so it's encrypted, not hashed."""
    return Fernet(get_settings().mfa_encryption_key.get_secret_value())


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> bytes:
    return fernet().encrypt(secret.encode())


def decrypt_secret(encrypted: bytes) -> str:
    return fernet().decrypt(encrypted).decode()


def setup_link(email: str, secret: str) -> str:
    """An otpauth:// link. The frontend shows it as a QR code for the app to scan."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER_NAME)


def code_is_valid(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=CLOCK_DRIFT_STEPS)