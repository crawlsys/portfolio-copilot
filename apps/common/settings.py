"""App settings via pydantic-settings. Reads from env / .env file.

NEVER import this from trading.domain or trading.application — settings
are an adapter/composition concern (per architecture rules).

A `@field_validator(mode="before")` strips inline comments + whitespace from
every value, so `.env` files with trailing `# comment` text don't break
pydantic's strict bool/int parsers.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @field_validator("*", mode="before")
    @classmethod
    def _strip_inline_comments(cls, v: Any) -> Any:
        """Strip trailing ' # comment' from string values + trim whitespace.

        Handles `.env` lines like `ALLOW_LIVE_TRADING=false  # always false in v1`
        that would otherwise fail pydantic's strict bool parser.
        """
        if isinstance(v, str):
            # Cut at the first ' #' or '\t#' sequence (a comment with leading ws).
            for sep in (" #", "\t#"):
                if sep in v:
                    v = v.split(sep, 1)[0]
            return v.strip()
        return v

    # App
    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")
    broker_mode: str = Field(default="fake")  # fake | schwab
    allow_live_trading: bool = Field(default=False)  # always False in v1

    # Postgres
    database_url: str = Field(default="")

    # Garage / S3
    s3_endpoint_url: str = Field(default="")
    s3_bucket: str = Field(default="tracker-blobs")
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")

    # Schwab
    schwab_client_id: str = Field(default="")
    schwab_client_secret: str = Field(default="")
    schwab_redirect_uri: str = Field(default="http://localhost:8000/schwab/callback")

    # Market data
    massive_api_key: str = Field(default="")

    # Congressional data
    quiver_api_key: str = Field(default="")

    # LLM
    llm_provider: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="")

    # Notifications
    push_provider: str = Field(default="")
    push_token: str = Field(default="")


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Tests can override via cache_clear()."""
    return Settings()
