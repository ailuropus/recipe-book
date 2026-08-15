"""The canonical shape of a recipe.

This module is the single definition of the house format. It is used in three
places, and that is deliberate:

  1. as the JSON schema the LLM must produce (structured outputs),
  2. as the validator for JSON import,
  3. as the validator behind the plain edit form.

If the three ever disagreed, a recipe that survived one path could be rejected
by another. They cannot disagree, because there is only one definition.

Note what is *absent*: id, parent_id, variant_note, timestamps. Identity and
lineage are the database's business. Keeping them out of RecipeDoc means the
model is structurally incapable of inventing a parent link or overwriting an
id, rather than merely instructed not to.
"""

from typing import Literal

from pydantic import BaseModel, Field

RecipeStatus = Literal["new", "tried", "solid"]


class Ingredient(BaseModel):
    name: str
    # Quantity is a string, not a number. Real recipes say "по вкусу",
    # "1/2", "2-3", "щепотка". Scaling and unit conversion are non-goals, so
    # there is nothing to gain from forcing these into a float and a great
    # deal of fidelity to lose.
    qty: str | None = None
    unit: str | None = None
    # Where the brand, fat percentage, or choice guidance lives:
    # "Caputo 00", "жирность 20%", "не бери размороженное".
    note: str | None = None


class Equipment(BaseModel):
    item: str
    note: str | None = None


class Step(BaseModel):
    n: int
    text_md: str


class RecipeDoc(BaseModel):
    """A complete recipe, independent of where it is stored."""

    title: str
    category: str
    # Two or three sentences.
    description: str
    hands_on_min: int
    total_min: int
    # Free text: "2 средние пиццы" carries more than the integer 2 would.
    servings: str
    # True when the recipe cannot be started and finished in one sitting.
    plan_ahead: bool
    status: RecipeStatus = "new"
    equipment: list[Equipment] = Field(default_factory=list)
    ingredients: list[Ingredient] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    # Accumulated observations: what worked, which brand, what to do differently.
    notes_md: str = ""


class RevisionProposal(BaseModel):
    """What the LLM returns when asked to revise a recipe.

    The whole recipe comes back, not a patch. That is what makes knock-on
    effects work: changing a quantity has to update the ingredient row, the
    step that uses it, and the notes, and a model rewriting one coherent
    document handles that far more reliably than one emitting edits.

    The cost is that untouched parts could drift. That is precisely what the
    diff gate is for.
    """

    # Plain language, for the human reading the review screen.
    summary: str
    recipe: RecipeDoc
