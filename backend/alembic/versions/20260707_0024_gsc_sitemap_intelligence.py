"""Add sitemap intelligence tables.

Revision ID: 0024_gsc_sitemap_intelligence
Revises: 0023_gsc_monitor_settings
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0024_gsc_sitemap_intelligence"
down_revision: Union[str, None] = "0023_gsc_monitor_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Each enum is used by exactly one table, so create_table auto-creates each type
# once. Downgrade drops them explicitly. (create_type=False + explicit create is
# not reliably honored under the async pg driver in this project.)
sitemap_source = sa.Enum("gsc_api", "detected", "generated", name="sitemapsource")
sitemap_status = sa.Enum("active", "warning", "error", "deleted", name="sitemapstatus")
sitemap_issue_type = sa.Enum(
    "not_submitted", "pending", "fetch_error", "parse_error", "empty_sitemap",
    "invalid_url", "url_outside_property", "non_https_url", "duplicate_url",
    "url_not_found", "url_server_error", "url_redirects", "url_noindex",
    "url_non_canonical", "url_blocked_by_robots", "gsc_errors", "gsc_warnings",
    "missing_in_gsc",
    name="sitemapissuetype",
)
sitemap_issue_severity = sa.Enum("low", "medium", "high", "critical", name="sitemapissueseverity")
sitemap_issue_status = sa.Enum("open", "approved", "fixed", "ignored", name="sitemapissuestatus")


def upgrade() -> None:
    op.create_table(
        "gsc_sitemap_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sitemap_url", sa.String(length=2048), nullable=False),
        sa.Column("is_submitted", sa.Boolean(), nullable=False),
        sa.Column("is_pending", sa.Boolean(), nullable=False),
        sa.Column("is_sitemaps_index", sa.Boolean(), nullable=False),
        sa.Column("last_submitted_at", sa.DateTime(), nullable=True),
        sa.Column("last_downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("errors_count", sa.Integer(), nullable=False),
        sa.Column("warnings_count", sa.Integer(), nullable=False),
        sa.Column("submitted_urls_count", sa.Integer(), nullable=False),
        sa.Column("source", sitemap_source, nullable=False),
        sa.Column("status", sitemap_status, nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["gsc_properties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gsc_sitemap_records_tenant_id", "gsc_sitemap_records", ["tenant_id"])
    op.create_index("ix_gsc_sitemap_records_project_id", "gsc_sitemap_records", ["project_id"])
    op.create_index("ix_gsc_sitemap_records_property_id", "gsc_sitemap_records", ["property_id"])
    op.create_index("ix_gsc_sitemap_records_sitemap_url", "gsc_sitemap_records", ["sitemap_url"])
    op.create_index("ix_gsc_sitemap_records_is_submitted", "gsc_sitemap_records", ["is_submitted"])
    op.create_index("ix_gsc_sitemap_records_source", "gsc_sitemap_records", ["source"])
    op.create_index("ix_gsc_sitemap_records_status", "gsc_sitemap_records", ["status"])
    op.create_index("ix_gsc_sitemaps_tenant_project", "gsc_sitemap_records", ["tenant_id", "project_id"])
    op.create_index("ix_gsc_sitemaps_project_url", "gsc_sitemap_records", ["project_id", "sitemap_url"], unique=True)
    op.create_index("ix_gsc_sitemaps_status", "gsc_sitemap_records", ["status", "created_at"])

    op.create_table(
        "sitemap_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sitemap_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_type", sitemap_issue_type, nullable=False),
        sa.Column("severity", sitemap_issue_severity, nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("sample_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sitemap_issue_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["sitemap_id"], ["gsc_sitemap_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sitemap_issues_tenant_id", "sitemap_issues", ["tenant_id"])
    op.create_index("ix_sitemap_issues_project_id", "sitemap_issues", ["project_id"])
    op.create_index("ix_sitemap_issues_sitemap_id", "sitemap_issues", ["sitemap_id"])
    op.create_index("ix_sitemap_issues_issue_type", "sitemap_issues", ["issue_type"])
    op.create_index("ix_sitemap_issues_severity", "sitemap_issues", ["severity"])
    op.create_index("ix_sitemap_issues_status", "sitemap_issues", ["status"])
    op.create_index("ix_sitemap_issues_tenant_project", "sitemap_issues", ["tenant_id", "project_id"])
    op.create_index("ix_sitemap_issues_status_type", "sitemap_issues", ["status", "issue_type"])
    op.create_index("ix_sitemap_issues_dedupe", "sitemap_issues", ["sitemap_id", "issue_type", "status"])


def downgrade() -> None:
    op.drop_table("sitemap_issues")
    op.drop_table("gsc_sitemap_records")
    bind = op.get_bind()
    for enum_type in (
        sitemap_issue_status,
        sitemap_issue_severity,
        sitemap_issue_type,
        sitemap_status,
        sitemap_source,
    ):
        enum_type.drop(bind, checkfirst=True)
