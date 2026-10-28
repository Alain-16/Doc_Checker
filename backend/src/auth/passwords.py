from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 12
# Argon2 is slow on purpose; an absurdly long password would make it slower still.
MAX_PASSWORD_LENGTH = 256

# Argon2id with the library's recommended cost settings.
hasher = PasswordHasher()
# Checked when the email is unknown, so "wrong email" takes as long as "wrong
# password" and the response time doesn't reveal which emails have accounts.
TIMING_DECOY_HASH = hasher.hash("decoy password, never assigned to anyone")



class PasswordRuleError(ValueError):
    """A new password that doesn't meet the rules; the message says which."""

def check_password_rules(password: str) -> None:

    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordRuleError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordRuleError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")

def hash_password(password: str) -> str:
    return hasher.hash(password)


def password_matches(password_hash: str | None, password: str) -> bool:
    if password_hash is None:
        password_hash_matches(TIMING_DECOY_HASH,password)
        return False
    return password_hash_matches(password_hash, password)

def password_hash_matches(password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False

