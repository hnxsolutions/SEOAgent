"""Daily executive briefings + notifications.

Revision ID: 0029_briefings_notifications
Revises: 0028_deployments
Create Date: 2026-07-16
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0029_briefings_notifications"
down_revision: Union[str, None] = "0028_deployments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("seo_score", sa.Float(), nullable=True),
        sa.Column("seo_score_prev", sa.Float(), nullable=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("summary_source", sa.String(length=16), nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "briefing_date", name="uq_daily_briefing_project_date"),
    )
    op.create_index(op.f("ix_daily_briefings_tenant_id"), "daily_briefings", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_daily_briefings_project_id"), "daily_briefings", ["project_id"], unique=False)
    op.create_index(op.f("ix_daily_briefings_briefing_date"), "daily_briefings", ["briefing_date"], unique=False)
    op.create_index(op.f("ix_daily_briefings_created_at"), "daily_briefings", ["created_at"], unique=False)
    op.create_index("ix_daily_briefings_project_date", "daily_briefings", ["project_id", "briefing_date"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("level", sa.Enum("info", "success", "warning", "critical", name="notificationlevel"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_notifications_project_id"), "notifications", ["project_id"], unique=False)
    op.create_index(op.f("ix_notifications_level"), "notifications", ["level"], unique=False)
    op.create_index(op.f("ix_notifications_category"), "notifications", ["category"], unique=False)
    op.create_index(op.f("ix_notifications_read"), "notifications", ["read"], unique=False)
    op.create_index(op.f("ix_notifications_dedupe_key"), "notifications", ["dedupe_key"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_project_read", "notifications", ["project_id", "read"], unique=False)


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("daily_briefings")
    sa.Enum(name="notificationlevel").drop(op.get_bind(), checkfirst=True)
