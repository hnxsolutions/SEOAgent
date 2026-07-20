"""Patch pipelines (autonomous apply/verify lifecycle tracking).

Revision ID: 0039_patch_pipelines
Revises: 0038_generated_seo_patches
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0039_patch_pipelines"
down_revision: Union[str, None] = "0038_generated_seo_patches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patch_pipelines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("framework", sa.String(length=64), nullable=True),
        sa.Column("status", sa.Enum("pending", "running", "succeeded", "failed", "rolled_back", "blocked", name="patchpipelinestatus"), nullable=False),
        sa.Column("current_stage", sa.String(length=32), nullable=True),
        sa.Column("stages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("diff_summary", sa.Text(), nullable=True),
        sa.Column("pr_url", sa.String(length=1024), nullable=True),
        sa.Column("pr_status", sa.String(length=64), nullable=True),
        sa.Column("deployment_id", sa.UUID(), nullable=True),
        sa.Column("verification_id", sa.UUID(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=True),
        sa.Column("validation_output", sa.Text(), nullable=True),
        sa.Column("patches_total", sa.Integer(), nullable=True),
        sa.Column("patches_applied", sa.Integer(), nullable=True),
        sa.Column("patches_failed", sa.Integer(), nullable=True),
        sa.Column("seo_before", sa.Integer(), nullable=True),
        sa.Column("seo_after", sa.Integer(), nullable=True),
        sa.Column("performance_before", sa.Integer(), nullable=True),
        sa.Column("performance_after", sa.Integer(), nullable=True),
        sa.Column("ready_for_pr", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "status", "created_at"):
        op.create_index(op.f(f"ix_patch_pipelines_{col}"), "patch_pipelines", [col], unique=False)


def downgrade() -> None:
    op.drop_table("patch_pipelines")
    sa.Enum(name="patchpipelinestatus").drop(op.get_bind(), checkfirst=True)
