"""After-merge AI fix verification + learning history table.

Revision ID: 0027_ai_fix_verifications
Revises: 0026_robots_intelligence
Create Date: 2026-07-15
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0027_ai_fix_verifications"
down_revision: Union[str, None] = "0026_robots_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_fix_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("patch_id", sa.UUID(), nullable=False),
        sa.Column("pull_request_id", sa.UUID(), nullable=True),
        sa.Column("issue_id", sa.UUID(), nullable=True),
        sa.Column("patch_type", sa.String(length=64), nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "verified_success", "partially_successful",
                "failed", "needs_human_review", name="verificationstatus",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("baseline_seo_run_id", sa.UUID(), nullable=True),
        sa.Column("followup_seo_run_id", sa.UUID(), nullable=True),
        sa.Column("baseline_score", sa.Float(), nullable=True),
        sa.Column("followup_score", sa.Float(), nullable=True),
        sa.Column("issue_resolved", sa.Boolean(), nullable=True),
        sa.Column("improvement_pct", sa.Float(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("merged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["patch_id"], ["seo_code_patches.id"]),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_request_records.id"]),
        sa.ForeignKeyConstraint(["issue_id"], ["seo_code_issues.id"]),
        sa.ForeignKeyConstraint(["baseline_seo_run_id"], ["seo_runs.id"]),
        sa.ForeignKeyConstraint(["followup_seo_run_id"], ["seo_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_fix_verifications_tenant_id"), "ai_fix_verifications", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_project_id"), "ai_fix_verifications", ["project_id"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_patch_id"), "ai_fix_verifications", ["patch_id"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_pull_request_id"), "ai_fix_verifications", ["pull_request_id"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_issue_id"), "ai_fix_verifications", ["issue_id"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_patch_type"), "ai_fix_verifications", ["patch_type"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_issue_type"), "ai_fix_verifications", ["issue_type"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_status"), "ai_fix_verifications", ["status"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_scheduled_at"), "ai_fix_verifications", ["scheduled_at"], unique=False)
    op.create_index(op.f("ix_ai_fix_verifications_created_at"), "ai_fix_verifications", ["created_at"], unique=False)
    op.create_index("ix_ai_fix_verifications_project_status", "ai_fix_verifications", ["project_id", "status"], unique=False)
    op.create_index("ix_ai_fix_verifications_patchtype_status", "ai_fix_verifications", ["patch_type", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("ai_fix_verifications")
    sa.Enum(name="verificationstatus").drop(op.get_bind(), checkfirst=True)
