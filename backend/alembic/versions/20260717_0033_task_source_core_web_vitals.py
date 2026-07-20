"""Add core_web_vitals value to seotasksourcetype enum.

Lets planner tasks generated from PageSpeed Insights opportunities be traced back
to Core Web Vitals as their source.

Revision ID: 0033_task_source_cwv
Revises: 0032_pagespeed_runs
Create Date: 2026-07-17
"""
from typing import Union

from alembic import op


revision: str = "0033_task_source_cwv"
down_revision: Union[str, None] = "0032_pagespeed_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE seotasksourcetype ADD VALUE IF NOT EXISTS 'core_web_vitals'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value without recreating the type;
    # the extra value is harmless if unused.
    pass
