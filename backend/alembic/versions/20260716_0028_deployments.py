"""Deployment intelligence table.

Revision ID: 0028_deployments
Revises: 0027_ai_fix_verifications
Create Date: 2026-07-16
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0028_deployments"
down_revision: Union[str, None] = "0027_ai_fix_verifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("pull_request_id", sa.UUID(), nullable=True),
        sa.Column(
            "provider",
            sa.Enum("vercel", "netlify", "cloudflare_pages", "aws_amplify", "docker",
                    "github_pages", "custom_webhook", "unknown", name="deploymentprovider"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "building", "success", "failed", "skipped", name="deploymentstatus"),
            nullable=False,
        ),
        sa.Column("commit_sha", sa.String(length=128), nullable=True),
        sa.Column("deployment_url", sa.String(length=2048), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_request_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_deployments_tenant_id"), "deployments", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_deployments_project_id"), "deployments", ["project_id"], unique=False)
    op.create_index(op.f("ix_deployments_pull_request_id"), "deployments", ["pull_request_id"], unique=False)
    op.create_index(op.f("ix_deployments_provider"), "deployments", ["provider"], unique=False)
    op.create_index(op.f("ix_deployments_status"), "deployments", ["status"], unique=False)
    op.create_index(op.f("ix_deployments_commit_sha"), "deployments", ["commit_sha"], unique=False)
    op.create_index(op.f("ix_deployments_external_id"), "deployments", ["external_id"], unique=False)
    op.create_index(op.f("ix_deployments_created_at"), "deployments", ["created_at"], unique=False)
    op.create_index("ix_deployments_project_status", "deployments", ["project_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("deployments")
    sa.Enum(name="deploymentstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="deploymentprovider").drop(op.get_bind(), checkfirst=True)
