"""Live site validation results.

Revision ID: 0034_site_validations
Revises: 0033_task_source_cwv
Create Date: 2026-07-17
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0034_site_validations"
down_revision: Union[str, None] = "0033_task_source_cwv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_validations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("is_https", sa.Boolean(), nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_site_validations_tenant_id"), "site_validations", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_site_validations_project_id"), "site_validations", ["project_id"], unique=False)
    op.create_index(op.f("ix_site_validations_deployment_id"), "site_validations", ["deployment_id"], unique=False)
    op.create_index(op.f("ix_site_validations_created_at"), "site_validations", ["created_at"], unique=False)
    op.create_index("ix_site_validations_project_created", "site_validations", ["project_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("site_validations")
