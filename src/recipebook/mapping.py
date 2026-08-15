"""Translation between the stored row and the portable document.

Recipe (SQLAlchemy) is how a recipe is stored; RecipeDoc (Pydantic) is what it
*is*. Keeping the conversion in one place means the LLM, the form, the export,
and the revision snapshots all go through the same door.
"""

from typing import Any

from recipebook.models import Recipe
from recipebook.schemas import RecipeDoc


def doc_from_recipe(recipe: Recipe) -> RecipeDoc:
    return RecipeDoc.model_validate(
        {
            "title": recipe.title,
            "category": recipe.category,
            "description": recipe.description,
            "hands_on_min": recipe.hands_on_min,
            "total_min": recipe.total_min,
            "servings": recipe.servings,
            "plan_ahead": recipe.plan_ahead,
            "status": recipe.status,
            "equipment": recipe.equipment,
            "ingredients": recipe.ingredients,
            "steps": recipe.steps,
            "notes_md": recipe.notes_md,
        }
    )


def doc_to_dict(doc: RecipeDoc) -> dict[str, Any]:
    """Plain JSON-able dict, for JSONB columns and revision snapshots."""
    return doc.model_dump(mode="json")


def apply_doc(recipe: Recipe, doc: RecipeDoc) -> Recipe:
    """Write a document onto a row, leaving identity and lineage untouched.

    id, parent_id, variant_note, and the timestamps are deliberately not
    written: a document carries content, never identity.
    """
    recipe.title = doc.title
    recipe.category = doc.category
    recipe.description = doc.description
    recipe.hands_on_min = doc.hands_on_min
    recipe.total_min = doc.total_min
    recipe.servings = doc.servings
    recipe.plan_ahead = doc.plan_ahead
    recipe.status = doc.status
    recipe.equipment = [e.model_dump(mode="json") for e in doc.equipment]
    recipe.ingredients = [i.model_dump(mode="json") for i in doc.ingredients]
    recipe.steps = [s.model_dump(mode="json") for s in doc.steps]
    recipe.notes_md = doc.notes_md
    return recipe


def recipe_from_doc(doc: RecipeDoc) -> Recipe:
    return apply_doc(Recipe(), doc)
