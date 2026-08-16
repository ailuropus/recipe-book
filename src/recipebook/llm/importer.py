"""Pasted text in, house-format recipe out.

Nothing is saved here. The result goes to a review screen, and the cook
approves or corrects it before any row is written.
"""

import uuid
from dataclasses import dataclass

from anthropic import Anthropic
from sqlalchemy.orm import Session

from recipebook.llm.client import record_call, structured_call
from recipebook.llm.prompts import import_message, system_blocks
from recipebook.schemas import RecipeDoc

MAX_PASTE_CHARS = 60_000


@dataclass(frozen=True)
class ImportResult:
    doc: RecipeDoc
    llm_call_id: uuid.UUID
    cost_usd: str


def import_recipe(session: Session, raw: str, *, client: Anthropic | None = None) -> ImportResult:
    """Restructure a pasted recipe and record what the call cost."""
    text = raw.strip()
    if not text:
        raise ValueError("Nothing was pasted.")
    if len(text) > MAX_PASTE_CHARS:
        raise ValueError(
            f"That is {len(text):,} characters, and the limit is {MAX_PASTE_CHARS:,}. "
            "Paste one recipe at a time."
        )

    result = structured_call(
        output_format=RecipeDoc,
        system=system_blocks(),
        user=import_message(text),
        client=client,
    )
    call = record_call(session, result, kind="import")

    return ImportResult(
        doc=result.value,
        llm_call_id=call.id,
        cost_usd=f"{result.cost_usd:.4f}",
    )
