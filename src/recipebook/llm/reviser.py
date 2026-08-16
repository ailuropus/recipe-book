"""Describe a change in words; get a whole revised recipe back.

The proposal is written to `revisions` as soon as it arrives, with
status='pending'. No recipe is touched. Storing it is what lets a review
survive a reload or a phone locking mid-scroll, and it produces the audit trail
and the undo stack as a side effect.
"""

import uuid
from dataclasses import dataclass

from anthropic import Anthropic
from sqlalchemy.orm import Session

from recipebook.llm.client import record_call, structured_call
from recipebook.llm.prompts import revise_message, system_blocks
from recipebook.mapping import doc_from_recipe, doc_to_dict
from recipebook.models import Recipe, Revision
from recipebook.schemas import RecipeDoc, RevisionProposal

MAX_INSTRUCTION_CHARS = 4000


@dataclass(frozen=True)
class ProposalResult:
    revision_id: uuid.UUID
    before: RecipeDoc
    after: RecipeDoc
    summary: str
    cost_usd: str


def propose_revision(
    session: Session,
    recipe: Recipe,
    instruction: str,
    *,
    client: Anthropic | None = None,
) -> ProposalResult:
    """Ask for a revised recipe and write it down as pending."""
    text = instruction.strip()
    if not text:
        raise ValueError("Describe the change you want.")
    if len(text) > MAX_INSTRUCTION_CHARS:
        raise ValueError(
            f"That instruction is {len(text):,} characters, and the limit is "
            f"{MAX_INSTRUCTION_CHARS:,}."
        )

    before = doc_from_recipe(recipe)

    result = structured_call(
        output_format=RevisionProposal,
        system=system_blocks(),
        user=revise_message(before, text),
        client=client,
    )
    after = result.value.recipe

    revision = Revision(
        recipe_id=recipe.id,
        status="pending",
        instruction=text,
        summary=result.value.summary,
        before_snapshot=doc_to_dict(before),
        after_snapshot=doc_to_dict(after),
    )
    session.add(revision)
    session.flush()

    record_call(session, result, kind="revise", recipe_id=recipe.id, revision_id=revision.id)

    return ProposalResult(
        revision_id=revision.id,
        before=before,
        after=after,
        summary=result.value.summary,
        cost_usd=f"{result.cost_usd:.4f}",
    )
