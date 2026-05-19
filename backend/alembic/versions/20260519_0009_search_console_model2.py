"""Add Search Console API sync and opportunity tables.

Revision ID: 0009_search_console_model2
Revises: 0008_blog_planner
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009_search_console_model2"
down_revision: Union[str, None] = "0008_blog_planner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


source_type = postgresql.ENUM("csv_upload", "gsc_api", name="searchconsolesourcetype", create_type=False)
import_status = postgresql.ENUM("pending", "processing", "completed", "failed", name="searchconsoleimportstatus", create_type=False)
comparison_window = postgresql.ENUM("last_7_days", "last_28_days", "current_month", name="gsccomparisonwindow", create_type=False)
row_period = postgresql.ENUM("current", "previous", name="searchconsoleperiod", create_type=False)
opportunity_status = postgresql.ENUM(
    "suggested", "approved", "rejected", "completed", name="searchconsoleopportunitystatus", create_type=False
)
opportunity_type = postgresql.ENUM(
    "high_impressions_low_ctr",
    "striking_distance_keyword",
    "ranking_drop",
    "ctr_drop",
    "click_decline",
    "rising_impressions_clicks_flat",
    "metadata_rewrite",
    "content_refresh",
    "blog_support",
    "internal_link_support",
    "landing_page_expansion",
    name="searchconsoleopportunitytype",
    create_type=False,
)
connection_status = postgresql.ENUM("connected", "expired", "revoked", "failed", name="gscconnectionstatus", create_type=False)
sync_type = postgresql.ENUM("manual", "scheduled", name="gscsynctype", create_type=False)
sync_status = postgresql.ENUM("queued", "running", "completed", "failed", name="gscsyncjobstatus", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        source_type,
        import_status,
        comparison_window,
        row_period,
        opportunity_status,
        opportunity_type,
        connection_status,
        sync_type,
        sync_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "gsc_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", connection_status, nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gsc_connections_tenant_id", "gsc_connections", ["tenant_id"])
    op.create_index("ix_gsc_connections_user_id", "gsc_connections", ["user_id"])
    op.create_index("ix_gsc_connections_provider", "gsc_connections", ["provider"])
    op.create_index("ix_gsc_connections_status", "gsc_connections", ["status"])
    op.create_index("ix_gsc_connections_created_at", "gsc_connections", ["created_at"])
    op.create_index("ix_gsc_connections_tenant_user", "gsc_connections", ["tenant_id", "user_id"])
    op.create_index("ix_gsc_connections_created", "gsc_connections", ["created_at"], postgresql_using="brin")

    op.create_table(
        "gsc_properties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_url", sa.String(length=2048), nullable=False),
        sa.Column("permission_level", sa.String(length=100), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["gsc_connections.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gsc_properties_tenant_id", "gsc_properties", ["tenant_id"])
    op.create_index("ix_gsc_properties_project_id", "gsc_properties", ["project_id"])
    op.create_index("ix_gsc_properties_connection_id", "gsc_properties", ["connection_id"])
    op.create_index("ix_gsc_properties_site_url", "gsc_properties", ["site_url"])
    op.create_index("ix_gsc_properties_is_selected", "gsc_properties", ["is_selected"])
    op.create_index("ix_gsc_properties_created_at", "gsc_properties", ["created_at"])
    op.create_index("ix_gsc_properties_tenant_project", "gsc_properties", ["tenant_id", "project_id"])
    op.create_index("ix_gsc_properties_site", "gsc_properties", ["tenant_id", "connection_id", "site_url"], unique=True)

    op.create_table(
        "search_console_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("status", import_status, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("date_start", sa.DateTime(), nullable=True),
        sa.Column("date_end", sa.DateTime(), nullable=True),
        sa.Column("comparison_window", comparison_window, nullable=True),
        sa.Column("rows_imported", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["gsc_properties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_console_imports_tenant_id", "search_console_imports", ["tenant_id"])
    op.create_index("ix_search_console_imports_project_id", "search_console_imports", ["project_id"])
    op.create_index("ix_search_console_imports_property_id", "search_console_imports", ["property_id"])
    op.create_index("ix_search_console_imports_source_type", "search_console_imports", ["source_type"])
    op.create_index("ix_search_console_imports_status", "search_console_imports", ["status"])
    op.create_index("ix_search_console_imports_comparison_window", "search_console_imports", ["comparison_window"])
    op.create_index("ix_search_console_imports_created_at", "search_console_imports", ["created_at"])
    op.create_index("ix_sc_imports_tenant_project", "search_console_imports", ["tenant_id", "project_id"])
    op.create_index("ix_sc_imports_created", "search_console_imports", ["created_at"], postgresql_using="brin")

    op.create_table(
        "search_console_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.String(length=1000), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("date_start", sa.DateTime(), nullable=False),
        sa.Column("date_end", sa.DateTime(), nullable=False),
        sa.Column("comparison_window", comparison_window, nullable=True),
        sa.Column("period", row_period, nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["import_id"], ["search_console_imports.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["gsc_properties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_console_rows_tenant_id", "search_console_rows", ["tenant_id"])
    op.create_index("ix_search_console_rows_project_id", "search_console_rows", ["project_id"])
    op.create_index("ix_search_console_rows_import_id", "search_console_rows", ["import_id"])
    op.create_index("ix_search_console_rows_property_id", "search_console_rows", ["property_id"])
    op.create_index("ix_search_console_rows_crawl_page_id", "search_console_rows", ["crawl_page_id"])
    op.create_index("ix_search_console_rows_query", "search_console_rows", ["query"])
    op.create_index("ix_search_console_rows_page_url", "search_console_rows", ["page_url"])
    op.create_index("ix_search_console_rows_date_start", "search_console_rows", ["date_start"])
    op.create_index("ix_search_console_rows_date_end", "search_console_rows", ["date_end"])
    op.create_index("ix_search_console_rows_comparison_window", "search_console_rows", ["comparison_window"])
    op.create_index("ix_search_console_rows_period", "search_console_rows", ["period"])
    op.create_index("ix_search_console_rows_source_type", "search_console_rows", ["source_type"])
    op.create_index("ix_search_console_rows_content_hash", "search_console_rows", ["content_hash"])
    op.create_index("ix_search_console_rows_created_at", "search_console_rows", ["created_at"])
    op.create_index("ix_sc_rows_import_period", "search_console_rows", ["import_id", "period"])
    op.create_index("ix_sc_rows_tenant_project", "search_console_rows", ["tenant_id", "project_id"])
    op.create_index(
        "ix_sc_rows_dedupe",
        "search_console_rows",
        ["import_id", "query", "page_url", "period", "content_hash"],
        unique=True,
    )

    op.create_table(
        "search_console_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query", sa.String(length=1000), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("opportunity_type", opportunity_type, nullable=False),
        sa.Column("status", opportunity_status, nullable=False),
        sa.Column("current_clicks", sa.Integer(), nullable=True),
        sa.Column("current_impressions", sa.Integer(), nullable=True),
        sa.Column("current_ctr", sa.Float(), nullable=True),
        sa.Column("current_position", sa.Float(), nullable=True),
        sa.Column("previous_clicks", sa.Integer(), nullable=True),
        sa.Column("previous_impressions", sa.Integer(), nullable=True),
        sa.Column("previous_ctr", sa.Float(), nullable=True),
        sa.Column("previous_position", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["import_id"], ["search_console_imports.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["gsc_properties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_console_opportunities_tenant_id", "search_console_opportunities", ["tenant_id"])
    op.create_index("ix_search_console_opportunities_project_id", "search_console_opportunities", ["project_id"])
    op.create_index("ix_search_console_opportunities_import_id", "search_console_opportunities", ["import_id"])
    op.create_index("ix_search_console_opportunities_property_id", "search_console_opportunities", ["property_id"])
    op.create_index("ix_search_console_opportunities_crawl_page_id", "search_console_opportunities", ["crawl_page_id"])
    op.create_index("ix_search_console_opportunities_query", "search_console_opportunities", ["query"])
    op.create_index("ix_search_console_opportunities_page_url", "search_console_opportunities", ["page_url"])
    op.create_index("ix_search_console_opportunities_opportunity_type", "search_console_opportunities", ["opportunity_type"])
    op.create_index("ix_search_console_opportunities_status", "search_console_opportunities", ["status"])
    op.create_index("ix_search_console_opportunities_created_at", "search_console_opportunities", ["created_at"])
    op.create_index("ix_sc_opps_tenant_project", "search_console_opportunities", ["tenant_id", "project_id"])
    op.create_index("ix_sc_opps_status_priority", "search_console_opportunities", ["status", "priority_score"])
    op.create_index(
        "ix_sc_opps_dedupe_open",
        "search_console_opportunities",
        ["tenant_id", "project_id", "query", "page_url", "opportunity_type", "status"],
    )

    op.create_table(
        "gsc_sync_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sync_type", sync_type, nullable=False),
        sa.Column("date_start", sa.DateTime(), nullable=False),
        sa.Column("date_end", sa.DateTime(), nullable=False),
        sa.Column("comparison_window", comparison_window, nullable=False),
        sa.Column("status", sync_status, nullable=False),
        sa.Column("rows_fetched", sa.Integer(), nullable=True),
        sa.Column("opportunities_created", sa.Integer(), nullable=True),
        sa.Column("opportunities_updated", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["gsc_connections.id"]),
        sa.ForeignKeyConstraint(["import_id"], ["search_console_imports.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["gsc_properties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gsc_sync_jobs_tenant_id", "gsc_sync_jobs", ["tenant_id"])
    op.create_index("ix_gsc_sync_jobs_project_id", "gsc_sync_jobs", ["project_id"])
    op.create_index("ix_gsc_sync_jobs_connection_id", "gsc_sync_jobs", ["connection_id"])
    op.create_index("ix_gsc_sync_jobs_property_id", "gsc_sync_jobs", ["property_id"])
    op.create_index("ix_gsc_sync_jobs_import_id", "gsc_sync_jobs", ["import_id"])
    op.create_index("ix_gsc_sync_jobs_sync_type", "gsc_sync_jobs", ["sync_type"])
    op.create_index("ix_gsc_sync_jobs_comparison_window", "gsc_sync_jobs", ["comparison_window"])
    op.create_index("ix_gsc_sync_jobs_status", "gsc_sync_jobs", ["status", "created_at"])
    op.create_index("ix_gsc_sync_jobs_created_at", "gsc_sync_jobs", ["created_at"])
    op.create_index("ix_gsc_sync_jobs_tenant_project", "gsc_sync_jobs", ["tenant_id", "project_id"])


def downgrade() -> None:
    op.drop_table("gsc_sync_jobs")
    op.drop_table("search_console_opportunities")
    op.drop_table("search_console_rows")
    op.drop_table("search_console_imports")
    op.drop_table("gsc_properties")
    op.drop_table("gsc_connections")

    for enum_type in (
        sync_status,
        sync_type,
        connection_status,
        opportunity_type,
        opportunity_status,
        row_period,
        comparison_window,
        import_status,
        source_type,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
