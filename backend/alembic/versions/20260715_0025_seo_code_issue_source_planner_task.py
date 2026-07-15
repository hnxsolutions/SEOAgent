"""Add planner_task value to seocodeissuesource enum.

Lets the repository AI agent record code issues that originate from weekly
planner tasks, keeping every generated patch traceable back to the planner task
(and, through it, the originating audit issue).

Revision ID: 0025_planner_task_code_source
Revises: 0024_gsc_sitemap_intelligence
Create Date: 2026-07-15
"""
from typing import Union

from alembic import op


revision: str = "0025_planner_task_code_source"
down_revision: Union[str, None] = "0024_gsc_sitemap_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12+ permits ADD VALUE inside a transaction as long as the new
    # value is not used in the same transaction (it isn't here).
    op.execute("ALTER TYPE seocodeissuesource ADD VALUE IF NOT EXISTS 'planner_task'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value without recreating the type.
    # The extra value is harmless if unused, so downgrade is intentionally a no-op.
    pass
