"""Add GitHub SEO code agent foundation tables.

Revision ID: 0010_repo_code_agent
Revises: 0009_search_console_model2
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010_repo_code_agent"
down_revision: Union[str, None] = "0009_search_console_model2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


repo_provider = postgresql.ENUM("local", "github", name="repoprovider", create_type=False)
repo_connection_status = postgresql.ENUM("connected", "unavailable", "failed", name="repoconnectionstatus", create_type=False)
repo_scan_status = postgresql.ENUM("queued", "running", "completed", "failed", name="reposcanrunstatus", create_type=False)
repo_file_purpose = postgresql.ENUM(
    "layout", "page", "sitemap", "robots", "metadata", "jsonld", "config", "component", "unknown",
    name="repofilepurpose",
    create_type=False,
)
seo_issue_type = postgresql.ENUM(
    "missing_metadata",
    "weak_metadata",
    "missing_canonical",
    "missing_open_graph",
    "missing_twitter_meta",
    "missing_schema",
    "missing_sitemap",
    "missing_robots",
    "missing_alt_pattern",
    "heading_semantics_risk",
    "duplicate_metadata",
    "route_not_in_sitemap",
    name="seocodeissuetype",
    create_type=False,
)
seo_issue_severity = postgresql.ENUM("low", "medium", "high", "critical", name="seocodeissueseverity", create_type=False)
seo_issue_source = postgresql.ENUM(
    "crawl_issue",
    "content_optimization",
    "geo_aeo",
    "search_console",
    "repo_scan",
    name="seocodeissuesource",
    create_type=False,
)
seo_issue_status = postgresql.ENUM("open", "approved", "rejected", "fixed", name="seocodeissuestatus", create_type=False)
seo_patch_type = postgresql.ENUM(
    "metadata_update",
    "schema_addition",
    "sitemap_update",
    "robots_update",
    "canonical_addition",
    "og_twitter_addition",
    "semantic_html_safe_suggestion",
    name="seocodepatchtype",
    create_type=False,
)
seo_patch_risk = postgresql.ENUM("low", "medium", "high", name="seocodepatchrisk", create_type=False)
seo_patch_status = postgresql.ENUM("proposed", "approved", "rejected", "applied", name="seocodepatchstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        repo_provider,
        repo_connection_status,
        repo_scan_status,
        repo_file_purpose,
        seo_issue_type,
        seo_issue_severity,
        seo_issue_source,
        seo_issue_status,
        seo_patch_type,
        seo_patch_risk,
        seo_patch_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "repo_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", repo_provider, nullable=False),
        sa.Column("repo_url", sa.String(length=2048), nullable=True),
        sa.Column("local_path", sa.String(length=2048), nullable=True),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column("framework", sa.String(length=255), nullable=True),
        sa.Column("status", repo_connection_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_connections_tenant_id", "repo_connections", ["tenant_id"])
    op.create_index("ix_repo_connections_project_id", "repo_connections", ["project_id"])
    op.create_index("ix_repo_connections_provider", "repo_connections", ["provider"])
    op.create_index("ix_repo_connections_status", "repo_connections", ["status"])
    op.create_index("ix_repo_connections_created_at", "repo_connections", ["created_at"])
    op.create_index("ix_repo_connections_tenant_project", "repo_connections", ["tenant_id", "project_id"])
    op.create_index("ix_repo_connections_created", "repo_connections", ["created_at"], postgresql_using="brin")

    op.create_table(
        "repo_scan_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", repo_scan_status, nullable=False),
        sa.Column("framework_detected", sa.String(length=255), nullable=True),
        sa.Column("files_scanned", sa.Integer(), nullable=True),
        sa.Column("issues_found", sa.Integer(), nullable=True),
        sa.Column("patches_created", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_scan_runs_tenant_id", "repo_scan_runs", ["tenant_id"])
    op.create_index("ix_repo_scan_runs_project_id", "repo_scan_runs", ["project_id"])
    op.create_index("ix_repo_scan_runs_repo_connection_id", "repo_scan_runs", ["repo_connection_id"])
    op.create_index("ix_repo_scan_runs_status", "repo_scan_runs", ["status", "created_at"])
    op.create_index("ix_repo_scan_runs_created_at", "repo_scan_runs", ["created_at"])
    op.create_index("ix_repo_scan_runs_tenant_project", "repo_scan_runs", ["tenant_id", "project_id"])

    op.create_table(
        "repo_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("detected_purpose", repo_file_purpose, nullable=False),
        sa.Column("has_metadata", sa.Boolean(), nullable=False),
        sa.Column("has_jsonld", sa.Boolean(), nullable=False),
        sa.Column("has_canonical", sa.Boolean(), nullable=False),
        sa.Column("has_open_graph", sa.Boolean(), nullable=False),
        sa.Column("has_twitter_meta", sa.Boolean(), nullable=False),
        sa.Column("has_sitemap", sa.Boolean(), nullable=False),
        sa.Column("has_robots", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.ForeignKeyConstraint(["scan_run_id"], ["repo_scan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_files_tenant_id", "repo_files", ["tenant_id"])
    op.create_index("ix_repo_files_project_id", "repo_files", ["project_id"])
    op.create_index("ix_repo_files_repo_connection_id", "repo_files", ["repo_connection_id"])
    op.create_index("ix_repo_files_scan_run_id", "repo_files", ["scan_run_id"])
    op.create_index("ix_repo_files_file_path", "repo_files", ["file_path"])
    op.create_index("ix_repo_files_file_type", "repo_files", ["file_type"])
    op.create_index("ix_repo_files_content_hash", "repo_files", ["content_hash"])
    op.create_index("ix_repo_files_detected_purpose", "repo_files", ["detected_purpose"])
    op.create_index("ix_repo_files_created_at", "repo_files", ["created_at"])
    op.create_index("ix_repo_files_scan_path", "repo_files", ["scan_run_id", "file_path"], unique=True)
    op.create_index("ix_repo_files_tenant_project", "repo_files", ["tenant_id", "project_id"])

    op.create_table(
        "seo_code_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("issue_type", seo_issue_type, nullable=False),
        sa.Column("severity", seo_issue_severity, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommended_fix", sa.Text(), nullable=False),
        sa.Column("source_reference_type", seo_issue_source, nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", seo_issue_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.ForeignKeyConstraint(["scan_run_id"], ["repo_scan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_code_issues_tenant_id", "seo_code_issues", ["tenant_id"])
    op.create_index("ix_seo_code_issues_project_id", "seo_code_issues", ["project_id"])
    op.create_index("ix_seo_code_issues_repo_connection_id", "seo_code_issues", ["repo_connection_id"])
    op.create_index("ix_seo_code_issues_scan_run_id", "seo_code_issues", ["scan_run_id"])
    op.create_index("ix_seo_code_issues_file_id", "seo_code_issues", ["file_id"])
    op.create_index("ix_seo_code_issues_issue_type", "seo_code_issues", ["issue_type"])
    op.create_index("ix_seo_code_issues_severity", "seo_code_issues", ["severity"])
    op.create_index("ix_seo_code_issues_source_reference_type", "seo_code_issues", ["source_reference_type"])
    op.create_index("ix_seo_code_issues_source_reference_id", "seo_code_issues", ["source_reference_id"])
    op.create_index("ix_seo_code_issues_status", "seo_code_issues", ["status"])
    op.create_index("ix_seo_code_issues_created_at", "seo_code_issues", ["created_at"])
    op.create_index("ix_seo_code_issues_scan_type", "seo_code_issues", ["scan_run_id", "issue_type"])
    op.create_index("ix_seo_code_issues_tenant_project", "seo_code_issues", ["tenant_id", "project_id"])

    op.create_table(
        "seo_code_patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("patch_type", seo_patch_type, nullable=False),
        sa.Column("original_content_hash", sa.String(length=64), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column("proposed_content", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("risk_level", seo_patch_risk, nullable=False),
        sa.Column("status", seo_patch_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["seo_code_issues.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.ForeignKeyConstraint(["scan_run_id"], ["repo_scan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_code_patches_tenant_id", "seo_code_patches", ["tenant_id"])
    op.create_index("ix_seo_code_patches_project_id", "seo_code_patches", ["project_id"])
    op.create_index("ix_seo_code_patches_repo_connection_id", "seo_code_patches", ["repo_connection_id"])
    op.create_index("ix_seo_code_patches_scan_run_id", "seo_code_patches", ["scan_run_id"])
    op.create_index("ix_seo_code_patches_issue_id", "seo_code_patches", ["issue_id"])
    op.create_index("ix_seo_code_patches_file_path", "seo_code_patches", ["file_path"])
    op.create_index("ix_seo_code_patches_patch_type", "seo_code_patches", ["patch_type"])
    op.create_index("ix_seo_code_patches_original_content_hash", "seo_code_patches", ["original_content_hash"])
    op.create_index("ix_seo_code_patches_risk_level", "seo_code_patches", ["risk_level"])
    op.create_index("ix_seo_code_patches_status", "seo_code_patches", ["status"])
    op.create_index("ix_seo_code_patches_created_at", "seo_code_patches", ["created_at"])
    op.create_index("ix_seo_code_patches_scan_status", "seo_code_patches", ["scan_run_id", "status"])
    op.create_index("ix_seo_code_patches_tenant_project", "seo_code_patches", ["tenant_id", "project_id"])
    op.create_index(
        "ix_seo_code_patches_dedupe",
        "seo_code_patches",
        ["issue_id", "file_path", "patch_type", "original_content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("seo_code_patches")
    op.drop_table("seo_code_issues")
    op.drop_table("repo_files")
    op.drop_table("repo_scan_runs")
    op.drop_table("repo_connections")

    for enum_type in (
        seo_patch_status,
        seo_patch_risk,
        seo_patch_type,
        seo_issue_status,
        seo_issue_source,
        seo_issue_severity,
        seo_issue_type,
        repo_file_purpose,
        repo_scan_status,
        repo_connection_status,
        repo_provider,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
