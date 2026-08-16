"""The one place the Anthropic API is called from.

Every call is timed, priced, and written to `llm_calls` so that "what has this
recipe cost me to perfect" is answerable later. There are no quotas and no rate
limiting by design — the point is to be able to see the spend, not to police
it.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from anthropic import Anthropic
from anthropic.types import TextBlockParam, Usage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from recipebook.config import get_settings
from recipebook.models import LlmCall

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rates:
    """US dollars per million tokens."""

    input: Decimal
    cache_write: Decimal
    cache_read: Decimal
    output: Decimal


# Snapshot of published rates. A stored cost is never recalculated from these,
# so a rate change does not rewrite history; the token counts and the model id
# are kept alongside, which is what makes an old row recomputable if needed.
RATES: dict[str, Rates] = {
    "claude-opus-5": Rates(
        input=Decimal("5"),
        cache_write=Decimal("6.25"),
        cache_read=Decimal("0.50"),
        output=Decimal("25"),
    ),
}

PER_MILLION = Decimal("1000000")


def cost_usd(model: str, usage: Usage) -> Decimal:
    """Price one call, or return zero for a model with no rates on file.

    Zero rather than a guess: the row keeps the model id and every token count,
    so an unpriced call can be worked out later, whereas a plausible-looking
    wrong number would quietly poison the totals.
    """
    rates = RATES.get(model)
    if rates is None:
        log.warning("No rates on file for model %r; recording cost 0.", model)
        return Decimal("0")

    total = (
        rates.input * usage.input_tokens
        + rates.cache_write * (usage.cache_creation_input_tokens or 0)
        + rates.cache_read * (usage.cache_read_input_tokens or 0)
        + rates.output * usage.output_tokens
    )
    return (total / PER_MILLION).quantize(Decimal("0.000001"))


@dataclass(frozen=True)
class LlmResult[T: BaseModel]:
    """A parsed answer plus what it cost to get it."""

    value: T
    model: str
    usage: Usage
    cost_usd: Decimal
    latency_ms: int


@lru_cache
def get_client() -> Anthropic:
    return Anthropic(api_key=get_settings().require_api_key())


def structured_call[T: BaseModel](
    *,
    output_format: type[T],
    system: list[TextBlockParam],
    user: str,
    client: Anthropic | None = None,
) -> LlmResult[T]:
    """Ask for one structured answer, and time it.

    Nothing is written to the database here: the caller decides what the call
    belongs to, and a paste import does not know its recipe id until the cook
    has approved the result.
    """
    settings = get_settings()
    api = client if client is not None else get_client()

    started = time.monotonic()
    message = api.messages.parse(
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        output_config={"effort": settings.anthropic_effort},
        output_format=output_format,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    parsed = message.parsed_output
    if parsed is None:
        raise LlmCallFailed(
            f"The model returned no structured output (stop reason: {message.stop_reason})."
        )

    return LlmResult(
        value=parsed,
        model=message.model,
        usage=message.usage,
        cost_usd=cost_usd(message.model, message.usage),
        latency_ms=latency_ms,
    )


class LlmCallFailed(RuntimeError):
    """The call came back without a usable answer."""


def record_call(
    session: Session,
    result: LlmResult[BaseModel],
    *,
    kind: str,
    recipe_id: uuid.UUID | None = None,
    revision_id: uuid.UUID | None = None,
) -> LlmCall:
    """Write the cost row and flush it, so it has an id the caller can keep.

    An import has no recipe id yet. The review screen carries this row's id
    forward and fills the recipe in once the cook saves, so the cost still ends
    up attached to what it was spent on.
    """
    call = LlmCall(
        recipe_id=recipe_id,
        revision_id=revision_id,
        kind=kind,
        model=result.model,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_input_tokens=result.usage.cache_read_input_tokens or 0,
        cache_creation_input_tokens=result.usage.cache_creation_input_tokens or 0,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )
    session.add(call)
    session.flush()
    log.info(
        "llm call kind=%s model=%s in=%d out=%d cache_read=%d cost=$%s %dms",
        kind,
        result.model,
        result.usage.input_tokens,
        result.usage.output_tokens,
        result.usage.cache_read_input_tokens or 0,
        result.cost_usd,
        result.latency_ms,
    )
    return call
