"""A stand-in for the Anthropic client.

No test in this suite spends money. The fake records what it was asked, so the
prompt and the request parameters are testable, and returns whatever the test
wants back.
"""

from dataclasses import dataclass, field
from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import Usage
from pydantic import BaseModel


def default_usage() -> Usage:
    return Usage(
        input_tokens=1200,
        output_tokens=900,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=800,
    )


@dataclass
class FakeParsedMessage:
    parsed_output: BaseModel | None
    usage: Usage
    model: str
    stop_reason: str = "end_turn"


@dataclass
class FakeMessages:
    value: BaseModel | None
    usage: Usage = field(default_factory=default_usage)
    model: str = "claude-opus-5"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def parse(self, **kwargs: Any) -> FakeParsedMessage:
        self.calls.append(kwargs)
        return FakeParsedMessage(parsed_output=self.value, usage=self.usage, model=self.model)


@dataclass
class FakeAnthropic:
    messages: FakeMessages


def fake_client(
    value: BaseModel | None,
    *,
    usage: Usage | None = None,
    model: str = "claude-opus-5",
) -> tuple[Anthropic, FakeMessages]:
    """The fake, plus the recorder, typed so call sites need no cast."""
    messages = FakeMessages(value=value, usage=usage or default_usage(), model=model)
    return cast(Anthropic, FakeAnthropic(messages=messages)), messages
