"""A question about one recipe, answered against that recipe.

This is the one call that changes nothing. It has no review gate because there
is nothing to review: no row is written except the cost log, and the answer is
shown and then gone.
"""

from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from recipebook.llm.client import record_call, structured_call
from recipebook.llm.prompts import ask_message, system_blocks
from recipebook.mapping import doc_from_recipe
from recipebook.models import Recipe

MAX_QUESTION_CHARS = 2000


class Answer(BaseModel):
    """Structured for one reason: it keeps the model out of the recipe format.

    Asked for free text, a model handed a full recipe tends to answer with a
    revised recipe. A schema with one field called `answer` makes that awkward
    to do by accident.
    """

    answer: str = Field(description="The answer in Russian, addressing the cook на ты.")


@dataclass(frozen=True)
class AskResult:
    question: str
    answer: str
    cost_usd: str


def ask_about(
    session: Session, recipe: Recipe, question: str, *, client: Anthropic | None = None
) -> AskResult:
    text = question.strip()
    if not text:
        raise ValueError("Ask something.")
    if len(text) > MAX_QUESTION_CHARS:
        raise ValueError(
            f"That question is {len(text):,} characters, and the limit is {MAX_QUESTION_CHARS:,}."
        )

    result = structured_call(
        output_format=Answer,
        system=system_blocks(),
        user=ask_message(doc_from_recipe(recipe), text),
        client=client,
    )
    record_call(session, result, kind="ask", recipe_id=recipe.id)

    return AskResult(
        question=text,
        answer=result.value.answer,
        cost_usd=f"{result.cost_usd:.4f}",
    )
