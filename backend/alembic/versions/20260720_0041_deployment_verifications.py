"""Post-merge deployment verifications.

Revision ID: 0041_deployment_verifications
Revises: 0040_code_reviews
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0041_deployment_verifications"
down_revision: Union[str, None] = "0040_code_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("review_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Enum("pending", "running", "succeeded", "failed", "gated", name="verificationrunstatus"), nullable=False),
        sa.Column("deployment_provider", sa.String(length=64), nullable=True),
        sa.Column("deployment_status", sa.String(length=64), nullable=True),
        sa.Column("deployment_url", sa.String(length=1024), nullable=True),
        sa.Column("deployment_id", sa.UUID(), nullable=True),
        sa.Column("live_site", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pagespeed_before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pagespeed_after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cwv_comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("seo_before", sa.Integer(), nullable=True),
        sa.Column("seo_after", sa.Integer(), nullable=True),
        sa.Column("seo_comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("gsc_status", sa.String(length=64), nullable=True),
        sa.Column("learning_outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "review_id", "status", "created_at"):
        op.create_index(op.f(f"ix_deployment_verifications_{col}"), "deployment_verifications", [col], unique=False)


def downgrade() -> None:
    op.drop_table("deployment_verifications")
    sa.Enum(name="verificationrunstatus").drop(op.get_bind(), checkfirst=True)
