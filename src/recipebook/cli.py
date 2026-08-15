"""Command line entry points.

Export, import, and backup land here in a later step. For now: seeding a
development database with synthetic recipes so the interface has something to
show.
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import select

from recipebook.db import session_context
from recipebook.demo import demo_recipes, demo_variant_of_pizza
from recipebook.mapping import recipe_from_doc
from recipebook.models import Recipe


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recipebook")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="load synthetic recipes for development")
    seed_parser.add_argument(
        "--force",
        action="store_true",
        help="seed even if the database already contains recipes",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "seed":
        return seed(force=args.force)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
