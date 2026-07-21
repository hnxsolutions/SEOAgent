"""AI SEO Growth snapshots.

Revision ID: 0043_growth_snapshots
Revises: 0042_ops_health_snapshots
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0043_growth_snapshots"
down_revision: Union[str, None] = "0042_ops_health_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "growth_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("growth_score", sa.Integer(), nullable=True),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("keyword_opportunities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_gaps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("topic_clusters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blog_roadmap", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("traffic_forecast", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("eeat", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "created_at"):
        op.create_index(op.f(f"ix_growth_snapshots_{col}"), "growth_snapshots", [col], unique=False)


def downgrade() -> None:
    op.drop_table("growth_snapshots")
