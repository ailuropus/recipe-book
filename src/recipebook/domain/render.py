"""Rendering a RecipeDoc to canonical markdown.

The renderer has one hard requirement: **it must be deterministic**. The same
document renders to the same bytes every time. If it were not, every diff would
be full of phantom changes and the review gate would be worthless.

Two renderings exist, and the split matters:

  render_body  — equipment, ingredients, steps, notes. This is what the
                 line-level diff runs on.
  render_full  — the body with a title and metadata header. This is for
                 reading and copying.

Metadata is deliberately absent from the body. The review screen shows a
metadata diff (old value against new) separately, and including the same
fields in both would report every change twice.

Section labels here are English because they are interface chrome the
application generates, not authored recipe content. Only text that came from
the cook or the model is Russian. tests/test_chrome_is_english.py enforces it.
"""

from recipebook.schemas import Equipment, Ingredient, RecipeDoc, Step


def _format_ingredient(ing: Ingredient) -> str:
    """One ingredient, one line — so changing one changes exactly one line."""
    parts = [ing.name.strip()]

    measure = " ".join(p.strip() for p in (ing.qty, ing.unit) if p and p.strip())
    if measure:
        parts.append(measure)

    line = "- " + " — ".join(parts)
    if ing.note and ing.note.strip():
        line += f" ({ing.note.strip()})"
    return line


def _format_equipment(eq: Equipment) -> str:
    line = "- " + eq.item.strip()
    if eq.note and eq.note.strip():
        line += f" — {eq.note.strip()}"
    return line


def _format_step(step: Step) -> list[str]:
    """A step may run to several lines. Continuations are indented to keep the
    markdown list valid.

    The model's own line breaks are preserved verbatim and never re-wrapped.
    Re-wrapping would mean that editing one word near the start of a paragraph
    reflows every line after it, turning a one-word change into a twenty-line
    diff.
    """
    text_lines = step.text_md.strip().splitlines() or [""]
    rendered = [f"{step.n}. {text_lines[0].strip()}"]
    rendered.extend(f"   {line.rstrip()}" for line in text_lines[1:])
    return rendered


def render_body(doc: RecipeDoc) -> str:
    """The part of a recipe that gets a line-level diff."""
    lines: list[str] = []

    if doc.equipment:
        lines.append("## Equipment")
        lines.append("")
        lines.extend(_format_equipment(e) for e in doc.equipment)
        lines.append("")

    if doc.ingredients:
        lines.append("## Ingredients")
        lines.append("")
        lines.extend(_format_ingredient(i) for i in doc.ingredients)
        lines.append("")

    if doc.steps:
        lines.append("## Steps")
        lines.append("")
        for step in doc.steps:
            lines.extend(_format_step(step))
            lines.append("")

    if doc.notes_md.strip():
        lines.append("## Notes")
        lines.append("")
        lines.extend(line.rstrip() for line in doc.notes_md.strip().splitlines())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n" if lines else ""


def render_metadata_lines(doc: RecipeDoc) -> list[str]:
    """The metadata header, as rendered for reading (not for diffing)."""
    return [
        f"category:     {doc.category}",
        f"status:       {doc.status}",
        f"servings:     {doc.servings}",
        f"hands-on:     {doc.hands_on_min} min",
        f"total:        {doc.total_min} min",
        f"plan ahead:   {'yes' if doc.plan_ahead else 'no'}",
    ]


def render_full(doc: RecipeDoc) -> str:
    """The whole recipe as markdown, for reading, copying, and export."""
    lines = [f"# {doc.title}", ""]

    if doc.description.strip():
        lines.extend([doc.description.strip(), ""])

    lines.extend(render_metadata_lines(doc))
    lines.append("")

    body = render_body(doc)
    if body:
        lines.append(body.rstrip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
