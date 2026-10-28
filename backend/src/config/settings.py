from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import HttpUrl, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.chunk import ChunkingStrategy


ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):


    model_config = SettingsConfigDict(
        # Read .env if it exists. On servers there's no .env file; real
        # environment variables are used instead, and they always win over .env.
        env_file=ENV_FILE,
        env_file_encoding="utf-8",

        extra="ignore",
    )
    app_base_url: HttpUrl = HttpUrl("http://localhost:3000")
    # --- Application ---
   
    app_env: Literal["local", "staging", "production"]

    # --- Database and queue ---

    database_url: PostgresDsn
    redis_url: RedisDsn

    # --- Object storage ---

    s3_endpoint_url: HttpUrl | None = None
    s3_region: str

    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_originals_bucket: str

    ocr_confidence_threshold: float = 0.80
    textract_region: str | None = None

    openai_api_key: SecretStr
    
    default_admin_email: str | None = None
    default_admin_name: str | None = None
    default_admin_password: SecretStr | None = None

    # --- Chunking (Feature 10) ---
    # Changing these needs a re-index (scripts/reindex.py); no OCR is re-run.
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.HYBRID
    chunk_max_tokens: int = 512
    # Share of each chunk repeated at the start of the next (PRD: 0, 10 or 20%).
    chunk_overlap_percent: int = 10
    
    # Encrypts MFA secrets at rest. A Fernet key: generate one with
    #   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    mfa_encryption_key: SecretStr
    session_idle_minutes: int = 30  # PRD: 15-30 minutes
    max_failed_logins: int = 5  # PRD: lock the account after this many
    # "console" prints emails (local development); "ses" sends them through AWS SES.
    email_backend: Literal["console", "ses"] = "console"
    email_sender: str = "no-reply@doc-checker.local"

@lru_cache
def get_settings() -> Settings:
    """Return the settings, reading the environment only on the first call.

    lru_cache remembers the result, so every later call returns the same object
    instead of re-reading .env. Using a function rather than a module-level
    variable lets tests swap in different settings.
    """
    return Settings()