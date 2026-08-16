"""The recipe form, in the shape it crosses the wire.

Two screens post exactly these fields: editing an existing recipe, and
reviewing what the model made of a pasted recipe before it is saved. They share
one definition so that a field added to one cannot be forgotten by the other.
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from recipebook.domain.bodytext import (
    BodyTextError,
    equipment_from_text,
    equipment_to_text,
    ingredients_from_text,
    ingredients_to_text,
    steps_from_text,
    steps_to_text,
)
from recipebook.schemas import RecipeDoc


class FormError(ValueError):
    """Something the person filling in the form can fix, worded for them."""


class RecipeForm(BaseModel):
    """Everything a recipe holds, as strings from a textarea or an input.

    Optional text fields default to empty because clearing a description or a
    note is a legal edit, and because an unchecked checkbox sends nothing at
    all rather than sending false.
    """

    title: str
    category: str
    hands_on_min: int
    total_min: int
    status: str
    description: str = ""
    servings: str = ""
    notes_md: str = ""
    variant_note: str = ""
    equipment: str = ""
    ingredients: str = ""
    steps: str = ""
    plan_ahead: bool = False

    @classmethod
    def from_doc(cls, doc: RecipeDoc, *, variant_note: str = "") -> "RecipeForm":
        return cls(
            title=doc.title,
            category=doc.category,
            description=doc.description,
            servings=doc.servings,
            hands_on_min=doc.hands_on_min,
            total_min=doc.total_min,
            status=doc.status,
            plan_ahead=doc.plan_ahead,
            notes_md=doc.notes_md,
            variant_note=variant_note,
            equipment=equipment_to_text(doc.equipment),
            ingredients=ingredients_to_text(doc.ingredients),
            steps=steps_to_text(doc.steps),
        )

    def to_doc(self) -> RecipeDoc:
        """Parse and validate the whole form, or raise with something readable.

        Nothing is written by the caller until this returns, so a malformed
        ingredient line cannot leave a recipe half-updated.
        """
        try:
            payload: dict[str, Any] = {
                "title": self.title.strip(),
                "category": self.category.strip(),
                "description": self.description.strip(),
                "servings": self.servings.strip(),
                "hands_on_min": self.hands_on_min,
                "total_min": self.total_min,
                "status": self.status,
                "plan_ahead": self.plan_ahead,
                "notes_md": self.notes_md.strip(),
                "equipment": equipment_from_text(self.equipment),
                "ingredients": ingredients_from_text(self.ingredients),
                "steps": steps_from_text(self.steps),
            }
        except BodyTextError as exc:
            raise FormError(str(exc)) from exc

        if not payload["title"]:
            raise FormError("A recipe needs a title.")

        try:
            return RecipeDoc.model_validate(payload)
        except ValidationError as exc:
            raise FormError(_first_message(exc)) from exc


class ImportSaveForm(RecipeForm):
    """The review screen's form: a recipe, plus which call paid for it.

    A subclass rather than a second parameter on the route. FastAPI flattens a
    form model into individual fields only when it is the sole body parameter;
    adding a scalar alongside it makes both arrive nested instead, which is a
    422 with a confusing message.
    """

    llm_call_id: str = ""


def _first_message(exc: ValidationError) -> str:
    """One readable sentence out of a pydantic error.

    The form shows a person one problem at a time; a dump of the whole error
    list is noise when the field is right there on screen.
    """
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"]) or "value"
    return f"{field}: {first['msg']}"
