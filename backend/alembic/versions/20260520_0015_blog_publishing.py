"""Add blog publishing and infrastructure tables.

Revision ID: 0015_blog_publishing
Revises: 0014_seo_scheduler
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015_blog_publishing"
down_revision: Union[str, None] = "0014_seo_scheduler"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


publish_provider = postgresql.ENUM("wordpress", "nextjs_repo", "markdown_export", name="blogpublishprovider", create_type=False)
connection_status = postgresql.ENUM("connected", "unavailable", "failed", name="blogpublishconnectionstatus", create_type=False)
infrastructure_status = postgresql.ENUM("completed", "failed", name="bloginfrastructurecheckstatus", create_type=False)
infrastructure_strategy = postgresql.ENUM(
    "wordpress",
    "nextjs_mdx",
    "nextjs_markdown",
    "markdown_export",
    "create_blog_infrastructure",
    name="bloginfrastructurestrategy",
    create_type=False,
)
publish_mode = postgresql.ENUM("draft_upload", "markdown_export", "repo_patch", "infrastructure_patch", name="blogpublishmode", create_type=False)
publish_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "rolled_back",
    name="blogpublishrunstatus",
    create_type=False,
)
publish_result_status = postgresql.ENUM(
    "draft_created",
    "file_exported",
    "patch_created",
    "infrastructure_patch_created",
    "failed",
    name="blogpublishresultstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in [
        publish_provider,
        connection_status,
        infrastructure_status,
        infrastructure_strategy,
        publish_mode,
        publish_run_status,
        publish_result_status,
    ]:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "blog_publish_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", publish_provider, nullable=False),
        sa.Column("site_url", sa.String(length=2048), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("export_folder_path", sa.String(length=2048), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("encrypted_app_password", sa.Text(), nullable=True),
        sa.Column("status", connection_status, nullable=False),
        sa.Column("auto_upload_drafts_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_publish_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
    )
    for column in [
        "tenant_id",
        "project_id",
        "provider",
        "repo_connection_id",
        "status",
        "created_at",
    ]:
        op.create_index(f"ix_blog_publish_connections_{column}", "blog_publish_connections", [column])
    op.create_index(
        "ix_blog_publish_connections_tenant_project",
        "blog_publish_connections",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "ix_blog_publish_connections_project_provider",
        "blog_publish_connections",
        ["tenant_id", "project_id", "provider"],
    )

    op.create_table(
        "blog_infrastructure_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", infrastructure_status, nullable=False),
        sa.Column("framework_detected", sa.String(length=255), nullable=True),
        sa.Column("has_blog_index", sa.Boolean(), nullable=False),
        sa.Column("has_blog_detail_route", sa.Boolean(), nullable=False),
        sa.Column("has_content_directory", sa.Boolean(), nullable=False),
        sa.Column("blog_route_path", sa.String(length=512), nullable=True),
        sa.Column("content_directory", sa.String(length=512), nullable=True),
        sa.Column("recommended_strategy", infrastructure_strategy, nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
    )
    for column in [
        "tenant_id",
        "project_id",
        "repo_connection_id",
        "status",
        "recommended_strategy",
        "created_at",
    ]:
        op.create_index(f"ix_blog_infrastructure_checks_{column}", "blog_infrastructure_checks", [column])
    op.create_index(
        "ix_blog_infrastructure_checks_tenant_project",
        "blog_infrastructure_checks",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "ix_blog_infrastructure_checks_repo_created",
        "blog_infrastructure_checks",
        ["repo_connection_id", "created_at"],
    )

    op.create_table(
        "blog_publish_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blog_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", publish_provider, nullable=False),
        sa.Column("mode", publish_mode, nullable=False),
        sa.Column("status", publish_run_status, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["blog_draft_id"], ["blog_drafts.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["blog_publish_connections.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    for column in [
        "tenant_id",
        "project_id",
        "blog_draft_id",
        "connection_id",
        "provider",
        "mode",
        "status",
        "created_at",
    ]:
        op.create_index(f"ix_blog_publish_runs_{column}", "blog_publish_runs", [column])
    op.create_index("ix_blog_publish_runs_tenant_project", "blog_publish_runs", ["tenant_id", "project_id"])
    op.create_index("ix_blog_publish_runs_draft_status", "blog_publish_runs", ["blog_draft_id", "status"])

    op.create_table(
        "blog_publish_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publish_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blog_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", publish_provider, nullable=False),
        sa.Column("status", publish_result_status, nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("external_url", sa.String(length=2048), nullable=True),
        sa.Column("file_path", sa.String(length=2048), nullable=True),
        sa.Column("patch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pr_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["blog_draft_id"], ["blog_drafts.id"]),
        sa.ForeignKeyConstraint(["patch_id"], ["seo_code_patches.id"]),
        sa.ForeignKeyConstraint(["pr_id"], ["pull_request_records.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["publish_run_id"], ["blog_publish_runs.id"]),
    )
    for column in [
        "tenant_id",
        "project_id",
        "publish_run_id",
        "blog_draft_id",
        "provider",
        "status",
        "patch_id",
        "pr_id",
        "slug",
        "created_at",
    ]:
        op.create_index(f"ix_blog_publish_results_{column}", "blog_publish_results", [column])
    op.create_index("ix_blog_publish_results_tenant_project", "blog_publish_results", ["tenant_id", "project_id"])
    op.create_index("ix_blog_publish_results_run_status", "blog_publish_results", ["publish_run_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_blog_publish_results_run_status", table_name="blog_publish_results")
    op.drop_index("ix_blog_publish_results_tenant_project", table_name="blog_publish_results")
    for column in [
        "created_at",
        "slug",
        "pr_id",
        "patch_id",
        "status",
        "provider",
        "blog_draft_id",
        "publish_run_id",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_blog_publish_results_{column}", table_name="blog_publish_results")
    op.drop_table("blog_publish_results")

    op.drop_index("ix_blog_publish_runs_draft_status", table_name="blog_publish_runs")
    op.drop_index("ix_blog_publish_runs_tenant_project", table_name="blog_publish_runs")
    for column in [
        "created_at",
        "status",
        "mode",
        "provider",
        "connection_id",
        "blog_draft_id",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_blog_publish_runs_{column}", table_name="blog_publish_runs")
    op.drop_table("blog_publish_runs")

    op.drop_index("ix_blog_infrastructure_checks_repo_created", table_name="blog_infrastructure_checks")
    op.drop_index("ix_blog_infrastructure_checks_tenant_project", table_name="blog_infrastructure_checks")
    for column in [
        "created_at",
        "recommended_strategy",
        "status",
        "repo_connection_id",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_blog_infrastructure_checks_{column}", table_name="blog_infrastructure_checks")
    op.drop_table("blog_infrastructure_checks")

    op.drop_index("ix_blog_publish_connections_project_provider", table_name="blog_publish_connections")
    op.drop_index("ix_blog_publish_connections_tenant_project", table_name="blog_publish_connections")
    for column in [
        "created_at",
        "status",
        "repo_connection_id",
        "provider",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_blog_publish_connections_{column}", table_name="blog_publish_connections")
    op.drop_table("blog_publish_connections")

    for enum_type in [
        publish_result_status,
        publish_run_status,
        publish_mode,
        infrastructure_strategy,
        infrastructure_status,
        connection_status,
        publish_provider,
    ]:
        enum_type.drop(op.get_bind(), checkfirst=True)
