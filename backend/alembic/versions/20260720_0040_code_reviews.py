"""Code reviews (human approval workflow).

Revision ID: 0040_code_reviews
Revises: 0039_patch_pipelines
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0040_code_reviews"
down_revision: Union[str, None] = "0039_patch_pipelines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("pipeline_id", sa.UUID(), nullable=True),
        sa.Column("framework", sa.String(length=64), nullable=True),
        sa.Column("technology", sa.String(length=255), nullable=True),
        sa.Column("status", sa.Enum("ready_for_review", "approved", "merged", "rejected", "archived", name="codereviewstatus"), nullable=False),
        sa.Column("risk_level", sa.Enum("low", "medium", "high", "blocked", name="reviewrisk"), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("files_count", sa.Integer(), nullable=True),
        sa.Column("estimated_seo_impact", sa.String(length=64), nullable=True),
        sa.Column("estimated_performance_impact", sa.String(length=64), nullable=True),
        sa.Column("seo_before", sa.Integer(), nullable=True),
        sa.Column("seo_after_predicted", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=1024), nullable=True),
        sa.Column("pr_status", sa.String(length=64), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("merge_sha", sa.String(length=64), nullable=True),
        sa.Column("deployment_status", sa.String(length=64), nullable=True),
        sa.Column("patch_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.String(length=255), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "status", "risk_level", "created_at"):
        op.create_index(op.f(f"ix_code_reviews_{col}"), "code_reviews", [col], unique=False)


def downgrade() -> None:
    op.drop_table("code_reviews")
    sa.Enum(name="reviewrisk").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="codereviewstatus").drop(op.get_bind(), checkfirst=True)
