"""Record how many planner tasks were refreshed, not just how many were created.

A planner run upserts: findings that already have a task are refreshed, and only
genuinely new findings create one. Run it a second time over an unchanged site
and it correctly creates nothing — but the only number stored was
``tasks_created``, so the console showed "0 tasks created" beside a project
holding 803 tasks. That reads as a failed run, which it is not.

Revision ID: 0047_planner_tasks_refreshed
Revises: 0046_password_reset_tokens
"""
from alembic import op
import sqlalchemy as sa

revision = "0047_planner_tasks_refreshed"
down_revision = "0046_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_planner_runs",
        sa.Column("tasks_refreshed", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("seo_planner_runs", "tasks_refreshed")
