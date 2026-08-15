"""Configuration, read from the environment only.

Nothing here reads a secret from disk or from a hardcoded default. The API key
comes from the environment, which comes from .env locally (populated by hand
from Bitwarden) and from the systemd unit on the VPS.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://recipebook:recipebook@localhost:5432/recipebook"
    )

    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-opus-5")
    anthropic_effort: Effort = Field(default="high")

    # Thinking is on by default on Opus 5 and is charged against max_tokens, so
    # a tight ceiling truncates a recipe mid-revision. Generous by design.
    anthropic_max_tokens: int = Field(default=16000)

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)

    def require_api_key(self) -> str:
        """Fail loudly at the point of use rather than at import time.

        The web app, the tests, and the export CLI must all start without a key;
        only the two LLM call sites actually need one.
        """
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        return self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
