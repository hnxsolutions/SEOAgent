"""Add rank dimensions, impact tracking, and manual SERP snapshots.

Revision ID: 0017_rank_impact_serp_tracking
Revises: 0016_repo_architecture_profile
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0017_rank_impact_serp_tracking"
down_revision: Union[str, None] = "0016_repo_architecture_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


impact_experiment_type = postgresql.ENUM(
    "metadata_update",
    "content_refresh",
    "internal_link_update",
    "schema_update",
    "blog_published",
    "repo_patch_applied",
    "geo_aeo_improvement",
    "manual_seo_action",
    name="seoimpactexperimenttype",
    create_type=False,
)
impact_source_type = postgresql.ENUM(
    "planner_task",
    "search_console_opportunity",
    "content_optimization_suggestion",
    "internal_link_recommendation",
    "geo_aeo_recommendation",
    "blog_draft",
    "repo_patch",
    "manual",
    name="seoimpactsourcetype",
    create_type=False,
)
impact_status = postgresql.ENUM(
    "baseline_pending",
    "baseline_captured",
    "action_pending",
    "monitoring",
    "ready_for_review",
    "completed",
    "inconclusive",
    "failed",
    name="seoimpactexperimentstatus",
    create_type=False,
)
snapshot_type = postgresql.ENUM("baseline", "followup", name="seoimpactsnapshottype", create_type=False)
impact_data_source = postgresql.ENUM("gsc_api", "csv_import", "manual", name="seoimpactdatasource", create_type=False)
impact_outcome = postgresql.ENUM("improved", "declined", "neutral", "inconclusive", name="seoimpactoutcome", create_type=False)

serp_engine = postgresql.ENUM("google", name="serpsnapshotsearchengine", create_type=False)
serp_device = postgresql.ENUM("desktop", "mobile", name="serpsnapshotdevice", create_type=False)
serp_capture_mode = postgresql.ENUM(
    "manual",
    "screenshot_upload",
    "browser_assisted_manual",
    name="serpsnapshotcapturemode",
    create_type=False,
)
serp_status = postgresql.ENUM("captured", "missing_target", "failed", name="serpsnapshotstatus", create_type=False)
serp_asset_type = postgresql.ENUM("screenshot", "html_note", name="serpsnapshotassettype", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in [
        impact_experiment_type,
        impact_source_type,
        impact_status,
        snapshot_type,
        impact_data_source,
        impact_outcome,
        serp_engine,
        serp_device,
        serp_capture_mode,
        serp_status,
        serp_asset_type,
    ]:
        enum_type.create(bind, checkfirst=True)

    op.add_column("search_console_rows", sa.Column("country", sa.String(length=16), nullable=True))
    op.add_column("search_console_rows", sa.Column("device", sa.String(length=32), nullable=True))
    op.add_column("search_console_rows", sa.Column("search_appearance", sa.String(length=255), nullable=True))
    op.create_index("ix_search_console_rows_country", "search_console_rows", ["country"])
    op.create_index("ix_search_console_rows_device", "search_console_rows", ["device"])
    op.create_index("ix_search_console_rows_search_appearance", "search_console_rows", ["search_appearance"])
    op.create_index(
        "ix_sc_rows_project_dimensions",
        "search_console_rows",
        ["project_id", "country", "device", "search_appearance"],
    )

    op.create_table(
        "seo_impact_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_type", impact_experiment_type, nullable=False),
        sa.Column("source_type", impact_source_type, nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_page_url", sa.String(length=2048), nullable=False),
        sa.Column("target_query", sa.String(length=1000), nullable=True),
        sa.Column("target_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("baseline_start_date", sa.DateTime(), nullable=False),
        sa.Column("baseline_end_date", sa.DateTime(), nullable=False),
        sa.Column("action_date", sa.DateTime(), nullable=True),
        sa.Column("review_start_date", sa.DateTime(), nullable=True),
        sa.Column("review_end_date", sa.DateTime(), nullable=True),
        sa.Column("review_after_days", sa.Integer(), nullable=False),
        sa.Column("status", impact_status, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_seo_impact_experiments_tenant_id": ["tenant_id"],
        "ix_seo_impact_experiments_project_id": ["project_id"],
        "ix_seo_impact_experiments_experiment_type": ["experiment_type"],
        "ix_seo_impact_experiments_source_type": ["source_type"],
        "ix_seo_impact_experiments_source_reference_id": ["source_reference_id"],
        "ix_seo_impact_experiments_target_page_url": ["target_page_url"],
        "ix_seo_impact_experiments_target_query": ["target_query"],
        "ix_seo_impact_experiments_baseline_start_date": ["baseline_start_date"],
        "ix_seo_impact_experiments_baseline_end_date": ["baseline_end_date"],
        "ix_seo_impact_experiments_action_date": ["action_date"],
        "ix_seo_impact_experiments_review_start_date": ["review_start_date"],
        "ix_seo_impact_experiments_review_end_date": ["review_end_date"],
        "ix_seo_impact_experiments_status": ["status"],
        "ix_seo_impact_experiments_created_at": ["created_at"],
        "ix_seo_impact_experiments_tenant_project": ["tenant_id", "project_id"],
        "ix_seo_impact_experiments_status_review": ["status", "review_end_date"],
    }.items():
        op.create_index(name, "seo_impact_experiments", cols)

    op.create_table(
        "seo_impact_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_type", snapshot_type, nullable=False),
        sa.Column("date_start", sa.DateTime(), nullable=False),
        sa.Column("date_end", sa.DateTime(), nullable=False),
        sa.Column("query", sa.String(length=1000), nullable=True),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("data_source", impact_data_source, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["experiment_id"], ["seo_impact_experiments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_seo_impact_snapshots_tenant_id": ["tenant_id"],
        "ix_seo_impact_snapshots_project_id": ["project_id"],
        "ix_seo_impact_snapshots_experiment_id": ["experiment_id"],
        "ix_seo_impact_snapshots_snapshot_type": ["snapshot_type"],
        "ix_seo_impact_snapshots_date_start": ["date_start"],
        "ix_seo_impact_snapshots_date_end": ["date_end"],
        "ix_seo_impact_snapshots_query": ["query"],
        "ix_seo_impact_snapshots_page_url": ["page_url"],
        "ix_seo_impact_snapshots_data_source": ["data_source"],
        "ix_seo_impact_snapshots_created_at": ["created_at"],
        "ix_seo_impact_snapshots_exp_type": ["experiment_id", "snapshot_type"],
        "ix_seo_impact_snapshots_tenant_project": ["tenant_id", "project_id"],
    }.items():
        op.create_index(name, "seo_impact_snapshots", cols)

    op.create_table(
        "seo_impact_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clicks_delta", sa.Integer(), nullable=True),
        sa.Column("impressions_delta", sa.Integer(), nullable=True),
        sa.Column("ctr_delta", sa.Float(), nullable=True),
        sa.Column("position_delta", sa.Float(), nullable=True),
        sa.Column("percentage_clicks_change", sa.Float(), nullable=True),
        sa.Column("percentage_impressions_change", sa.Float(), nullable=True),
        sa.Column("outcome", impact_outcome, nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["experiment_id"], ["seo_impact_experiments.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_seo_impact_results_tenant_id": ["tenant_id"],
        "ix_seo_impact_results_project_id": ["project_id"],
        "ix_seo_impact_results_experiment_id": ["experiment_id"],
        "ix_seo_impact_results_outcome": ["outcome"],
        "ix_seo_impact_results_created_at": ["created_at"],
        "ix_seo_impact_results_exp_created": ["experiment_id", "created_at"],
        "ix_seo_impact_results_tenant_project": ["tenant_id", "project_id"],
    }.items():
        op.create_index(name, "seo_impact_results", cols)

    op.create_table(
        "serp_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword", sa.String(length=1000), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=True),
        sa.Column("target_domain", sa.String(length=255), nullable=False),
        sa.Column("search_engine", serp_engine, nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("device", serp_device, nullable=False),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("capture_mode", serp_capture_mode, nullable=False),
        sa.Column("observed_target_rank", sa.Integer(), nullable=True),
        sa.Column("status", serp_status, nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_serp_snapshots_tenant_id": ["tenant_id"],
        "ix_serp_snapshots_project_id": ["project_id"],
        "ix_serp_snapshots_keyword": ["keyword"],
        "ix_serp_snapshots_target_url": ["target_url"],
        "ix_serp_snapshots_target_domain": ["target_domain"],
        "ix_serp_snapshots_search_engine": ["search_engine"],
        "ix_serp_snapshots_country": ["country"],
        "ix_serp_snapshots_city": ["city"],
        "ix_serp_snapshots_device": ["device"],
        "ix_serp_snapshots_capture_mode": ["capture_mode"],
        "ix_serp_snapshots_observed_target_rank": ["observed_target_rank"],
        "ix_serp_snapshots_status": ["status"],
        "ix_serp_snapshots_captured_at": ["captured_at"],
    }.items():
        op.create_index(name, "serp_snapshots", cols)

    op.create_table(
        "serp_snapshot_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("is_target_domain", sa.Boolean(), nullable=False),
        sa.Column("is_target_url", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["serp_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_serp_snapshot_results_tenant_id": ["tenant_id"],
        "ix_serp_snapshot_results_project_id": ["project_id"],
        "ix_serp_snapshot_results_snapshot_id": ["snapshot_id"],
        "ix_serp_snapshot_results_position": ["position"],
        "ix_serp_snapshot_results_url": ["url"],
        "ix_serp_snapshot_results_domain": ["domain"],
        "ix_serp_snapshot_results_is_target_domain": ["is_target_domain"],
        "ix_serp_snapshot_results_is_target_url": ["is_target_url"],
    }.items():
        op.create_index(name, "serp_snapshot_results", cols)

    op.create_table(
        "serp_snapshot_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", serp_asset_type, nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["serp_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_serp_snapshot_assets_tenant_id": ["tenant_id"],
        "ix_serp_snapshot_assets_project_id": ["project_id"],
        "ix_serp_snapshot_assets_snapshot_id": ["snapshot_id"],
        "ix_serp_snapshot_assets_asset_type": ["asset_type"],
        "ix_serp_snapshot_assets_created_at": ["created_at"],
    }.items():
        op.create_index(name, "serp_snapshot_assets", cols)


def downgrade() -> None:
    op.drop_table("serp_snapshot_assets")
    op.drop_table("serp_snapshot_results")
    op.drop_table("serp_snapshots")
    op.drop_table("seo_impact_results")
    op.drop_table("seo_impact_snapshots")
    op.drop_table("seo_impact_experiments")
    op.drop_index("ix_sc_rows_project_dimensions", table_name="search_console_rows")
    op.drop_index("ix_search_console_rows_search_appearance", table_name="search_console_rows")
    op.drop_index("ix_search_console_rows_device", table_name="search_console_rows")
    op.drop_index("ix_search_console_rows_country", table_name="search_console_rows")
    op.drop_column("search_console_rows", "search_appearance")
    op.drop_column("search_console_rows", "device")
    op.drop_column("search_console_rows", "country")
