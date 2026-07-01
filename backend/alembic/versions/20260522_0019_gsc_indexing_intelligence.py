"""Add GSC URL Inspection indexing intelligence tables.

Revision ID: 0019_gsc_indexing_intelligence
Revises: 0018_seo_copy_review
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0019_gsc_indexing_intelligence"
down_revision: Union[str, None] = "0018_seo_copy_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


inspection_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "partial",
    name="gscurlinspectionrunstatus",
    create_type=False,
)
indexing_issue_type = postgresql.ENUM(
    "not_indexed",
    "crawled_not_indexed",
    "discovered_not_indexed",
    "duplicate_canonical",
    "canonical_mismatch",
    "page_with_redirect",
    "blocked_by_robots",
    "noindex_detected",
    "soft_404",
    "server_error",
    "redirect_error",
    "sitemap_missing",
    "thin_content",
    "orphan_page",
    "structured_data_issue",
    "unknown",
    name="gscindexingissuetype",
    create_type=False,
)
indexing_issue_severity = postgresql.ENUM(
    "low",
    "medium",
    "high",
    "critical",
    name="gscindexingissueseverity",
    create_type=False,
)
indexing_issue_status = postgresql.ENUM(
    "open",
    "in_progress",
    "fix_proposed",
    "fixed",
    "validated",
    "still_failing",
    "inconclusive",
    "ignored",
    name="gscindexingissuestatus",
    create_type=False,
)
validation_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    name="gscfixvalidationrunstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in [
        inspection_run_status,
        indexing_issue_type,
        indexing_issue_severity,
        indexing_issue_status,
        validation_run_status,
    ]:
        enum_type.create(bind, checkfirst=True)

    op.execute("ALTER TYPE seoscheduletype ADD VALUE IF NOT EXISTS 'weekly_indexing_monitor'")

    op.create_table(
        "gsc_url_inspection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gsc_property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", inspection_run_status, nullable=False),
        sa.Column("requested_url_count", sa.Integer(), nullable=True),
        sa.Column("inspected_url_count", sa.Integer(), nullable=True),
        sa.Column("failed_url_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["gsc_property_id"], ["gsc_properties.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_gsc_url_inspection_runs_tenant_id": ["tenant_id"],
        "ix_gsc_url_inspection_runs_project_id": ["project_id"],
        "ix_gsc_url_inspection_runs_gsc_property_id": ["gsc_property_id"],
        "ix_gsc_url_inspection_runs_status": ["status"],
        "ix_gsc_url_inspection_runs_created_at": ["created_at"],
        "ix_gsc_url_inspection_runs_tenant_project": ["tenant_id", "project_id"],
        "ix_gsc_url_inspection_runs_status_created": ["status", "created_at"],
    }.items():
        op.create_index(name, "gsc_url_inspection_runs", cols)

    op.create_table(
        "gsc_url_inspection_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inspection_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("inspection_result_link", sa.String(length=2048), nullable=True),
        sa.Column("verdict", sa.String(length=64), nullable=True),
        sa.Column("coverage_state", sa.String(length=255), nullable=True),
        sa.Column("indexing_state", sa.String(length=128), nullable=True),
        sa.Column("robots_txt_state", sa.String(length=128), nullable=True),
        sa.Column("page_fetch_state", sa.String(length=128), nullable=True),
        sa.Column("google_canonical", sa.String(length=2048), nullable=True),
        sa.Column("user_canonical", sa.String(length=2048), nullable=True),
        sa.Column("sitemap_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("referring_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_crawl_time", sa.DateTime(), nullable=True),
        sa.Column("crawled_as", sa.String(length=128), nullable=True),
        sa.Column("mobile_usability_verdict", sa.String(length=64), nullable=True),
        sa.Column("rich_results_verdict", sa.String(length=64), nullable=True),
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["inspection_run_id"], ["gsc_url_inspection_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_gsc_url_inspection_results_tenant_id": ["tenant_id"],
        "ix_gsc_url_inspection_results_project_id": ["project_id"],
        "ix_gsc_url_inspection_results_inspection_run_id": ["inspection_run_id"],
        "ix_gsc_url_inspection_results_page_url": ["page_url"],
        "ix_gsc_url_inspection_results_verdict": ["verdict"],
        "ix_gsc_url_inspection_results_coverage_state": ["coverage_state"],
        "ix_gsc_url_inspection_results_indexing_state": ["indexing_state"],
        "ix_gsc_url_inspection_results_created_at": ["created_at"],
        "ix_gsc_url_inspection_results_tenant_project": ["tenant_id", "project_id"],
        "ix_gsc_url_inspection_results_page_created": ["page_url", "created_at"],
    }.items():
        op.create_index(name, "gsc_url_inspection_results", cols)

    op.create_table(
        "gsc_indexing_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inspection_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("issue_type", indexing_issue_type, nullable=False),
        sa.Column("severity", indexing_issue_severity, nullable=False),
        sa.Column("likely_cause", sa.Text(), nullable=False),
        sa.Column("recommended_fix", sa.Text(), nullable=False),
        sa.Column("linked_repo_issue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linked_patch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", indexing_issue_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["inspection_result_id"], ["gsc_url_inspection_results.id"]),
        sa.ForeignKeyConstraint(["linked_patch_id"], ["seo_code_patches.id"]),
        sa.ForeignKeyConstraint(["linked_repo_issue_id"], ["seo_code_issues.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_gsc_indexing_issues_tenant_id": ["tenant_id"],
        "ix_gsc_indexing_issues_project_id": ["project_id"],
        "ix_gsc_indexing_issues_inspection_result_id": ["inspection_result_id"],
        "ix_gsc_indexing_issues_page_url": ["page_url"],
        "ix_gsc_indexing_issues_issue_type": ["issue_type"],
        "ix_gsc_indexing_issues_severity": ["severity"],
        "ix_gsc_indexing_issues_status": ["status"],
        "ix_gsc_indexing_issues_linked_repo_issue_id": ["linked_repo_issue_id"],
        "ix_gsc_indexing_issues_linked_patch_id": ["linked_patch_id"],
        "ix_gsc_indexing_issues_created_at": ["created_at"],
        "ix_gsc_indexing_issues_tenant_project": ["tenant_id", "project_id"],
        "ix_gsc_indexing_issues_status_type": ["status", "issue_type"],
        "ix_gsc_indexing_issues_page_status": ["page_url", "status"],
    }.items():
        op.create_index(name, "gsc_indexing_issues", cols)

    op.create_table(
        "gsc_fix_validation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("patch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pull_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", validation_run_status, nullable=False),
        sa.Column("validation_after_days", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["gsc_indexing_issues.id"]),
        sa.ForeignKeyConstraint(["patch_id"], ["seo_code_patches.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_request_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_gsc_fix_validation_runs_tenant_id": ["tenant_id"],
        "ix_gsc_fix_validation_runs_project_id": ["project_id"],
        "ix_gsc_fix_validation_runs_issue_id": ["issue_id"],
        "ix_gsc_fix_validation_runs_patch_id": ["patch_id"],
        "ix_gsc_fix_validation_runs_pull_request_id": ["pull_request_id"],
        "ix_gsc_fix_validation_runs_status": ["status"],
        "ix_gsc_fix_validation_runs_created_at": ["created_at"],
        "ix_gsc_fix_validation_runs_tenant_project": ["tenant_id", "project_id"],
        "ix_gsc_fix_validation_runs_status_created": ["status", "created_at"],
    }.items():
        op.create_index(name, "gsc_fix_validation_runs", cols)

    op.create_table(
        "gsc_fix_validation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_url", sa.String(length=2048), nullable=False),
        sa.Column("previous_issue_type", indexing_issue_type, nullable=False),
        sa.Column("current_verdict", sa.String(length=64), nullable=True),
        sa.Column("current_coverage_state", sa.String(length=255), nullable=True),
        sa.Column("fixed", sa.Boolean(), nullable=False),
        sa.Column("still_failing", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["gsc_indexing_issues.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["validation_run_id"], ["gsc_fix_validation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_gsc_fix_validation_results_tenant_id": ["tenant_id"],
        "ix_gsc_fix_validation_results_project_id": ["project_id"],
        "ix_gsc_fix_validation_results_validation_run_id": ["validation_run_id"],
        "ix_gsc_fix_validation_results_issue_id": ["issue_id"],
        "ix_gsc_fix_validation_results_page_url": ["page_url"],
        "ix_gsc_fix_validation_results_previous_issue_type": ["previous_issue_type"],
        "ix_gsc_fix_validation_results_current_verdict": ["current_verdict"],
        "ix_gsc_fix_validation_results_fixed": ["fixed"],
        "ix_gsc_fix_validation_results_still_failing": ["still_failing"],
        "ix_gsc_fix_validation_results_created_at": ["created_at"],
        "ix_gsc_fix_validation_results_tenant_project": ["tenant_id", "project_id"],
        "ix_gsc_fix_validation_results_issue": ["issue_id", "created_at"],
    }.items():
        op.create_index(name, "gsc_fix_validation_results", cols)


def downgrade() -> None:
    op.drop_table("gsc_fix_validation_results")
    op.drop_table("gsc_fix_validation_runs")
    op.drop_table("gsc_indexing_issues")
    op.drop_table("gsc_url_inspection_results")
    op.drop_table("gsc_url_inspection_runs")
