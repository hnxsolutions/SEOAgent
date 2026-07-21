"""Autonomous SEO ops health snapshots.

Revision ID: 0042_ops_health_snapshots
Revises: 0041_deployment_verifications
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0042_ops_health_snapshots"
down_revision: Union[str, None] = "0041_deployment_verifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_health_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "created_at"):
        op.create_index(op.f(f"ix_ops_health_snapshots_{col}"), "ops_health_snapshots", [col], unique=False)


def downgrade() -> None:
    op.drop_table("ops_health_snapshots")
