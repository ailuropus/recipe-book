"""llm call kind ask

Widens ck_llm_calls_kind to admit 'ask'.

Written by hand. Autogenerate produced an empty migration: it compares which
constraints exist, not what their expressions say, so a CHECK whose name is
unchanged but whose condition has been widened is invisible to it. The same
blind spot means the models-versus-migration test cannot catch this either — a
changed CHECK expression is one of the few things that has to be noticed by a
person.

The downgrade would fail if any 'ask' rows existed, so it deletes them first.
That is a deliberate data loss on the way down: the alternative is a downgrade
that cannot run at all, and these rows are a cost log, not recipes.

Revision ID: 7a8656aee90a
Revises: 0b72e04bd51a
Create Date: 2026-08-16 12:39:25.194814
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7a8656aee90a"
down_revision: str | None = "0b72e04bd51a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_llm_calls_kind", "llm_calls", type_="check")
    op.create_check_constraint(
        "ck_llm_calls_kind", "llm_calls", "kind IN ('import', 'revise', 'ask')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM llm_calls WHERE kind = 'ask'")
    op.drop_constraint("ck_llm_calls_kind", "llm_calls", type_="check")
    op.create_check_constraint("ck_llm_calls_kind", "llm_calls", "kind IN ('import', 'revise')")
