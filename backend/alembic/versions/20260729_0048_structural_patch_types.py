"""Add the structural patch types to the seocodepatchtype enum.

The repository agent could only ever add things: metadata_update,
schema_addition, sitemap_update, robots_update, canonical_addition,
og_twitter_addition, semantic_html_safe_suggestion. Real SEO defects also need
removing and rewriting — deleting a canonical that should not be there,
repointing a link at a route that 404s, replacing one metadata field, changing
an allow-listed config key, or doing several of those atomically.

The rules for each new type (which paths it may touch, the single operation it
may perform, and the checks it must pass) live in
`app/repo_agent/patch_vocabulary.py`. This migration only widens the enum so
those patches can be persisted; it grants no behaviour by itself.

`generated_seo_patches.patch_type` is a plain String column and needs no change.
Only `seo_code_patches.patch_type` uses the native enum.

Revision ID: 0048_structural_patch_types
Revises: 0047_planner_tasks_refreshed
Create Date: 2026-07-29
"""
from typing import Union

from alembic import op


revision: str = "0048_structural_patch_types"
down_revision: Union[str, None] = "0047_planner_tasks_refreshed"
branch_labels = None
depends_on = None


NEW_VALUES = (
    "canonical_removal",
    "internal_link_fix",
    "metadata_replace",
    "config_update",
    "multi_file_patch",
)


def upgrade() -> None:
    # PostgreSQL 12+ permits ADD VALUE inside a transaction as long as the new
    # value is not used in the same transaction (it is not here). IF NOT EXISTS
    # keeps the migration re-runnable.
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE seocodepatchtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value without recreating the type,
    # which would require rewriting every row that references it. An unused
    # extra value is harmless, so downgrade is intentionally a no-op — matching
    # how the other enum-widening migrations in this project behave.
    pass
