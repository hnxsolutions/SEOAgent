"""Generated SEO patches (framework-aware generator output).

Revision ID: 0038_generated_seo_patches
Revises: 0037_fingerprint_strategy
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0038_generated_seo_patches"
down_revision: Union[str, None] = "0037_fingerprint_strategy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_seo_patches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("framework", sa.String(length=64), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("patch_type", sa.String(length=48), nullable=False),
        sa.Column("target_file", sa.String(length=512), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("generated_code", sa.Text(), nullable=False),
        sa.Column("is_new_file", sa.Boolean(), nullable=True),
        sa.Column("code_fixable", sa.Boolean(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("safe", sa.Boolean(), nullable=True),
        sa.Column("safety_reason", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.Enum("pending", "passed", "failed", "gated", name="generatedpatchvalidation"), nullable=False),
        sa.Column("validation_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("seo_before", sa.Integer(), nullable=True),
        sa.Column("seo_after", sa.Integer(), nullable=True),
        sa.Column("performance_before", sa.Integer(), nullable=True),
        sa.Column("performance_after", sa.Integer(), nullable=True),
        sa.Column("ready_for_pr", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("source_task_id", sa.UUID(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "framework", "safe", "validation_status", "ready_for_pr", "code_hash", "created_at"):
        op.create_index(op.f(f"ix_generated_seo_patches_{col}"), "generated_seo_patches", [col], unique=False)


def downgrade() -> None:
    op.drop_table("generated_seo_patches")
    sa.Enum(name="generatedpatchvalidation").drop(op.get_bind(), checkfirst=True)
