"""Add repo architecture profile table.

Revision ID: 0016_repo_architecture_profile
Revises: 0015_blog_publishing
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016_repo_architecture_profile"
down_revision: Union[str, None] = "0015_blog_publishing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repo_architecture_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detected_stack", sa.String(length=255), nullable=False),
        sa.Column("framework", sa.String(length=255), nullable=True),
        sa.Column("router_type", sa.String(length=255), nullable=True),
        sa.Column("package_manager", sa.String(length=100), nullable=True),
        sa.Column("languages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("route_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("blog_system", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schema_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sitemap_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("robots_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cms_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("client_server_boundaries", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("safe_patch_zones", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("manual_review_zones", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unsafe_patch_zones", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("detection_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.ForeignKeyConstraint(["scan_run_id"], ["repo_scan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_architecture_profiles_tenant_id", "repo_architecture_profiles", ["tenant_id"])
    op.create_index("ix_repo_architecture_profiles_project_id", "repo_architecture_profiles", ["project_id"])
    op.create_index("ix_repo_architecture_profiles_repo_connection_id", "repo_architecture_profiles", ["repo_connection_id"])
    op.create_index("ix_repo_architecture_profiles_scan_run_id", "repo_architecture_profiles", ["scan_run_id"])
    op.create_index("ix_repo_architecture_profiles_detected_stack", "repo_architecture_profiles", ["detected_stack"])
    op.create_index("ix_repo_architecture_profiles_framework", "repo_architecture_profiles", ["framework"])
    op.create_index("ix_repo_architecture_profiles_created_at", "repo_architecture_profiles", ["created_at"])
    op.create_index("ix_repo_arch_profiles_scan_created", "repo_architecture_profiles", ["scan_run_id", "created_at"])
    op.create_index("ix_repo_arch_profiles_tenant_project", "repo_architecture_profiles", ["tenant_id", "project_id"])
    op.create_index("ix_repo_arch_profiles_connection", "repo_architecture_profiles", ["repo_connection_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_repo_arch_profiles_connection", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_arch_profiles_tenant_project", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_arch_profiles_scan_created", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_created_at", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_framework", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_detected_stack", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_scan_run_id", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_repo_connection_id", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_project_id", table_name="repo_architecture_profiles")
    op.drop_index("ix_repo_architecture_profiles_tenant_id", table_name="repo_architecture_profiles")
    op.drop_table("repo_architecture_profiles")
