"""Command line entry points.

Export, import, and backup live here rather than in the web app because they
are the things you want when the web app is the problem.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from recipebook.db import session_context
from recipebook.demo import demo_recipes, demo_variant_of_pizza
from recipebook.mapping import recipe_from_doc
from recipebook.models import LlmCall, Recipe
from recipebook.portable import export_json, import_export, parse_export


def seed(*, force: bool) -> int:
    """Load synthetic recipes.

    Refuses to run against a database that already holds recipes unless forced,
    so it cannot quietly mix demo content into real ones.
    """
    with session_context() as session:
        if session.scalar(select(Recipe).limit(1)) is not None and not force:
            print(
                "Database already contains recipes; refusing to seed. "
                "Pass --force to add the demo set anyway.",
                file=sys.stderr,
            )
            return 1

        docs = demo_recipes()
        parent = recipe_from_doc(docs[0])
        session.add(parent)
        for doc in docs[1:]:
            session.add(recipe_from_doc(doc))
        session.flush()

        variant = recipe_from_doc(demo_variant_of_pizza())
        variant.parent_id = parent.id
        variant.variant_note = "Треть пшеничной муки заменена на полбяную."
        session.add(variant)

        print(f"Seeded {len(docs) + 1} synthetic recipes.")
    return 0


def export_command(destination: str | None) -> int:
    """Write every recipe as JSON, to a file or to stdout."""
    with session_context() as session:
        payload = export_json(session)
        count = session.scalar(select(func.count()).select_from(Recipe)) or 0

    if destination in (None, "-"):
        sys.stdout.write(payload)
    else:
        path = Path(str(destination))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        print(f"Exported {count} recipes to {path} ({len(payload):,} bytes).", file=sys.stderr)
    return 0


def import_command(source: str, *, mode: str) -> int:
    """Merge a JSON export into this database."""
    payload = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")

    try:
        export = parse_export(payload)
    except ValueError as exc:
        print(f"Could not read that file: {exc}", file=sys.stderr)
        return 1

    with session_context() as session:
        report = import_export(session, export, mode="replace" if mode == "replace" else "merge")

    print(str(report), file=sys.stderr)
    return 0


def backup_command(directory: str, *, keep: int) -> int:
    """Write a timestamped export and prune the oldest.

    Not a substitute for pg_dump — this carries recipes, not revisions or the
    cost log. It is the copy that survives a schema change, a bad migration, or
    moving to a different machine.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = target / f"rakamakatui-{stamp}.json"

    with session_context() as session:
        payload = export_json(session)
        count = session.scalar(select(func.count()).select_from(Recipe)) or 0

    path.write_text(payload, encoding="utf-8")
    print(f"Backed up {count} recipes to {path}.", file=sys.stderr)

    if keep > 0:
        backups = sorted(target.glob("rakamakatui-*.json"))
        for stale in backups[:-keep]:
            stale.unlink()
            print(f"Removed old backup {stale.name}.", file=sys.stderr)
    return 0


def spend_command() -> int:
    """What the model calls have cost, in total and per recipe.

    The per-recipe rows are reported alongside an unattributed line rather than
    on their own. llm_calls.recipe_id is ON DELETE SET NULL, so the cost log
    outlives the recipes it was spent on — which means a breakdown that only
    joined to existing recipes would quietly fail to add up to the total, and
    the reader would have no way to tell.
    """
    with session_context() as session:
        total = session.scalar(select(func.sum(LlmCall.cost_usd))) or 0
        calls = session.scalar(select(func.count()).select_from(LlmCall)) or 0
        print(f"{calls} call(s), ${total:.4f} total")

        rows = session.execute(
            select(Recipe.title, func.sum(LlmCall.cost_usd), func.count(LlmCall.id))
            .join(LlmCall, LlmCall.recipe_id == Recipe.id)
            .group_by(Recipe.id, Recipe.title)
            .order_by(func.sum(LlmCall.cost_usd).desc())
        ).all()
        for title, cost, n in rows:
            print(f"  ${cost:.4f}  {n:>3} call(s)  {title}")

        orphan_cost = (
            session.scalar(select(func.sum(LlmCall.cost_usd)).where(LlmCall.recipe_id.is_(None)))
            or 0
        )
        orphan_calls = (
            session.scalar(
                select(func.count()).select_from(LlmCall).where(LlmCall.recipe_id.is_(None))
            )
            or 0
        )
        if orphan_calls:
            print(
                f"  ${orphan_cost:.4f}  {orphan_calls:>3} call(s)  "
                "(no recipe — imports never saved, or recipes since deleted)"
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recipebook")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="load synthetic recipes for development")
    seed_parser.add_argument(
        "--force",
        action="store_true",
        help="seed even if the database already contains recipes",
    )

    export_parser = subparsers.add_parser("export", help="write every recipe as JSON")
    export_parser.add_argument(
        "-o", "--out", default="-", help="output file, or - for stdout (default)"
    )

    import_parser = subparsers.add_parser("import", help="merge a JSON export into the database")
    import_parser.add_argument("source", help="input file, or - for stdin")
    import_parser.add_argument(
        "--mode",
        choices=["merge", "replace"],
        default="merge",
        help=("merge (default) leaves recipes not named in the file alone; replace deletes them"),
    )

    backup_parser = subparsers.add_parser("backup", help="write a timestamped export")
    backup_parser.add_argument("--dir", default="backups", help="directory to write into")
    backup_parser.add_argument(
        "--keep", type=int, default=14, help="how many to keep; 0 keeps everything"
    )

    subparsers.add_parser("spend", help="what the model calls have cost")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    match args.command:
        case "seed":
            return seed(force=args.force)
        case "export":
            return export_command(args.out)
        case "import":
            return import_command(args.source, mode=args.mode)
        case "backup":
            return backup_command(args.dir, keep=args.keep)
        case "spend":
            return spend_command()
        case _:
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
