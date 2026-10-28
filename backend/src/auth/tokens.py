import hashlib
import secrets

# 32 random bytes: far beyond guessing range.
TOKEN_BYTES = 32


def token_hash(token: str) -> str:
    """What the database keeps instead of the token. SHA-256 is enough here (no
    Argon2 needed): the token is random, so there is nothing to guess from its hash."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """A fresh token for the user, and its hash for the database."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, token_hash(token)