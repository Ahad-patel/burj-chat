"""Application settings, loaded and validated once at startup.

Python note: `pydantic-settings` reads each field from the environment (or a
`.env` file), coerces it to the declared type, and fails loudly if it cannot.
That failure happens at import time, so a typo in `LLM_PROVIDER` crashes the
process on boot rather than surfacing as a confusing error on the first visitor
request.

This is the one module allowed to know that both providers exist. Everything
downstream receives an `LLMClient` and cannot tell which one it got.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Provider(StrEnum):
    """The LLM providers this application can be pointed at.

    A `StrEnum` rather than a bare string so an unknown value fails validation
    at startup instead of falling through to an `else` branch at request time.
    """

    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Every knob this service has, in one validated object."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_env: Environment = Environment.LOCAL
    log_level: str = "INFO"

    # --- LLM provider --------------------------------------------------------
    llm_provider: Provider = Provider.GEMINI
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    gemini_model: str = "gemini-2.0-flash"

    #: Claude Opus 5 is the current default. It is not the cheapest option — at
    #: roughly 5k knowledge-base tokens per request, a cheaper model is a
    #: defensible choice for a high-traffic widget. That is a cost decision for
    #: the client to make deliberately, not one to bury in a default, so the
    #: alternatives are documented in .env.example rather than silently applied.
    anthropic_model: str = "claude-opus-5"

    llm_temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.2
    llm_max_output_tokens: Annotated[int, Field(gt=0, le=8192)] = 1024
    llm_timeout_seconds: Annotated[float, Field(gt=0)] = 20.0

    # --- Knowledge base ------------------------------------------------------
    kb_path: Path = REPO_ROOT / "knowledge-base" / "knowledge_base.xml"

    # --- API security --------------------------------------------------------
    cors_allowed_origins: str = "https://burjconstructions.com,https://www.burjconstructions.com"
    rate_limit_per_ip_per_minute: Annotated[int, Field(gt=0)] = 20
    rate_limit_per_session_per_hour: Annotated[int, Field(gt=0)] = 100

    #: Whether to read the client IP from `X-Forwarded-For`. Defaults to False
    #: because that header is client-controlled: trusting it without a proxy in
    #: front means an attacker sends a fresh value per request and the per-IP
    #: limit silently stops existing. Enable only when a reverse proxy that
    #: *overwrites* the header terminates every connection.
    trust_proxy_headers: bool = False

    # --- Conversation retention ----------------------------------------------
    conversation_ttl_minutes: Annotated[int, Field(gt=0)] = 30
    max_messages_per_conversation: Annotated[int, Field(gt=0, le=40)] = 40

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()
        )

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def active_api_key(self) -> str:
        """The key for whichever provider is selected."""
        return (
            self.gemini_api_key if self.llm_provider is Provider.GEMINI else self.anthropic_api_key
        )

    @model_validator(mode="after")
    def _require_key_for_active_provider(self) -> Self:
        """Fail at startup if the selected provider has no key.

        Only the *active* provider's key is required — running on Gemini must
        not force the client to hold an unused Anthropic credential. Checking
        this at boot converts a silent 500 on the first visitor question into a
        crash the deploy will catch.
        """
        if not self.active_api_key.strip():
            raise ValueError(
                f"LLM_PROVIDER is {self.llm_provider.value!r} but "
                f"{self.llm_provider.value.upper()}_API_KEY is not set"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Python note: `@lru_cache` memoises the call, which is the idiomatic
    singleton for FastAPI dependencies — and lets tests clear it with
    `get_settings.cache_clear()` rather than reaching into a global.
    """
    return Settings()
