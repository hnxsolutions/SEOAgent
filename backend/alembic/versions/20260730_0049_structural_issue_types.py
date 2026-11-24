"""Add the structural issue types to the seocodeissuetype enum.

Migration 0048 widened the *patch* vocabulary so a canonical could be removed and
a link repointed. Those patches still need an issue to hang off:
`seo_code_patches.issue_id` is NOT NULL with a foreign key to `seo_code_issues`,
so a patch cannot be stored without one.

The twelve existing issue types are all "something is missing" or "something is
risky". Neither new defect fits:

* `inherited_canonical` — a canonical declared in the ROOT layout, which every
  route without its own inherits. The nearest existing value, `duplicate_metadata`,
  describes two pages sharing metadata, not one declaration leaking downward, and
  reusing it would mislabel the finding in every report and task the agent emits.
* `broken_internal_link` — an href pointing at a route the repository does not
  build. Nothing in the current enum is about links at all.

Detection lives in `app/repo_agent/structural_detectors.py`; the rules that bound
the resulting patches live in `app/repo_agent/patch_vocabulary.py`. This migration
only widens the enum so the findings can be persisted.

Revision ID: 0049_structural_issue_types
Revises: 0048_structural_patch_types
Create Date: 2026-07-30
"""
from typing import Union

from alembic import op


revision: str = "0049_structural_issue_types"
down_revision: Union[str, None] = "0048_structural_patch_types"
branch_labels = None
depends_on = None


NEW_VALUES = (
    "inherited_canonical",
    "broken_internal_link",
)


def upgrade() -> None:
    # PostgreSQL 12+ permits ADD VALUE inside a transaction as long as the new
    # value is not used in the same transaction (it is not here). IF NOT EXISTS
    # keeps the migration re-runnable.
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE seocodeissuetype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value without recreating the type,
    # which would mean rewriting every row that references it. An unused extra
    # value is harmless, so downgrade is a no-op — matching 0019, 0025, 0033,
    # 0044, 0045 and 0048.
    pass
