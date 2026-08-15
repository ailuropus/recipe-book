"""Config tests must not depend on whether the developer happens to have a .env.

`IsolatedSettings` switches off .env loading, and the fixture clears any of our
variables that are set in the ambient shell, so these assertions are about the
declared defaults and nothing else.
"""

import pytest
from pydantic_settings import SettingsConfigDict

from recipebook.config import Settings

_OUR_ENV_VARS = (
    "DATABASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_EFFORT",
    "ANTHROPIC_MAX_TOKENS",
    "HOST",
    "PORT",
)


class IsolatedSettings(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _OUR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_load_without_env() -> None:
    """Every entry point except the two LLM calls must start without a key."""
    settings = IsolatedSettings()
    assert settings.anthropic_model == "claude-opus-5"
    assert settings.port == 8000
    assert settings.anthropic_api_key == ""


def test_require_api_key_raises_when_unset() -> None:
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        IsolatedSettings().require_api_key()


def test_require_api_key_returns_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert IsolatedSettings().require_api_key() == "sk-ant-test"
