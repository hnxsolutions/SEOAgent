"""Add deterministic SEO audit tables.

Revision ID: 0002_seo_audit_tables
Revises: 0001_initial_schema
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_seo_audit_tables"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


audit_status = postgresql.ENUM(
    "pending", "running", "completed", "failed", name="seoauditstatus", create_type=False
)
issue_severity = postgresql.ENUM(
    "low", "medium", "high", "critical", name="seoissueseverity", create_type=False
)
issue_category = postgresql.ENUM(
    "technical", "content", "metadata", "links", "schema", name="seoissuecategory", create_type=False
)
issue_status = postgresql.ENUM(
    "open", "ignored", "fixed", name="seoissuestatus", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    audit_status.create(bind, checkfirst=True)
    issue_severity.create(bind, checkfirst=True)
    issue_category.create(bind, checkfirst=True)
    issue_status.create(bind, checkfirst=True)

    op.create_table(
        "seo_audit_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", audit_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("site_score", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("total_issues", sa.Integer(), nullable=True),
        sa.Column("issue_counts_by_severity", sa.JSON(), nullable=True),
        sa.Column("issue_counts_by_category", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_audit_runs_crawl_job_id", "seo_audit_runs", ["crawl_job_id"])
    op.create_index("ix_seo_audit_runs_project_id", "seo_audit_runs", ["project_id"])
    op.create_index("ix_seo_audit_runs_tenant_id", "seo_audit_runs", ["tenant_id"])
    op.create_index("ix_seo_audit_runs_status", "seo_audit_runs", ["status"])
    op.create_index("ix_seo_audit_runs_tenant_crawl", "seo_audit_runs", ["tenant_id", "crawl_job_id"])
    op.create_index("ix_seo_audit_runs_created", "seo_audit_runs", ["created_at"], postgresql_using="brin")

    op.create_table(
        "seo_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("severity", issue_severity, nullable=False),
        sa.Column("category", issue_category, nullable=False),
        sa.Column("status", issue_status, nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score_impact", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["audit_run_id"], ["seo_audit_runs.id"]),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_issues_audit_run_id", "seo_issues", ["audit_run_id"])
    op.create_index("ix_seo_issues_crawl_job_id", "seo_issues", ["crawl_job_id"])
    op.create_index("ix_seo_issues_crawl_page_id", "seo_issues", ["crawl_page_id"])
    op.create_index("ix_seo_issues_project_id", "seo_issues", ["project_id"])
    op.create_index("ix_seo_issues_tenant_id", "seo_issues", ["tenant_id"])
    op.create_index("ix_seo_issues_issue_type", "seo_issues", ["issue_type"])
    op.create_index("ix_seo_issues_severity", "seo_issues", ["severity"])
    op.create_index("ix_seo_issues_category", "seo_issues", ["category"])
    op.create_index("ix_seo_issues_status", "seo_issues", ["status"])
    op.create_index("ix_seo_issues_tenant_status", "seo_issues", ["tenant_id", "status"])
    op.create_index("ix_seo_issues_crawl_page", "seo_issues", ["crawl_job_id", "crawl_page_id"])
    op.create_index("ix_seo_issues_created_at", "seo_issues", ["created_at"])

    op.create_table(
        "seo_page_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=True),
        sa.Column("critical_issues", sa.Integer(), nullable=True),
        sa.Column("high_issues", sa.Integer(), nullable=True),
        sa.Column("medium_issues", sa.Integer(), nullable=True),
        sa.Column("low_issues", sa.Integer(), nullable=True),
        sa.Column("score_breakdown", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["audit_run_id"], ["seo_audit_runs.id"]),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_page_scores_audit_run_id", "seo_page_scores", ["audit_run_id"])
    op.create_index("ix_seo_page_scores_crawl_job_id", "seo_page_scores", ["crawl_job_id"])
    op.create_index("ix_seo_page_scores_crawl_page_id", "seo_page_scores", ["crawl_page_id"])
    op.create_index("ix_seo_page_scores_project_id", "seo_page_scores", ["project_id"])
    op.create_index("ix_seo_page_scores_tenant_id", "seo_page_scores", ["tenant_id"])
    op.create_index("ix_seo_page_scores_created_at", "seo_page_scores", ["created_at"])
    op.create_index(
        "ix_seo_page_scores_run_page",
        "seo_page_scores",
        ["audit_run_id", "crawl_page_id"],
        unique=True,
    )
    op.create_index(
        "ix_seo_page_scores_tenant_crawl",
        "seo_page_scores",
        ["tenant_id", "crawl_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_seo_page_scores_tenant_crawl", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_run_page", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_created_at", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_tenant_id", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_project_id", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_crawl_page_id", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_crawl_job_id", table_name="seo_page_scores")
    op.drop_index("ix_seo_page_scores_audit_run_id", table_name="seo_page_scores")
    op.drop_table("seo_page_scores")

    op.drop_index("ix_seo_issues_created_at", table_name="seo_issues")
    op.drop_index("ix_seo_issues_crawl_page", table_name="seo_issues")
    op.drop_index("ix_seo_issues_tenant_status", table_name="seo_issues")
    op.drop_index("ix_seo_issues_status", table_name="seo_issues")
    op.drop_index("ix_seo_issues_category", table_name="seo_issues")
    op.drop_index("ix_seo_issues_severity", table_name="seo_issues")
    op.drop_index("ix_seo_issues_issue_type", table_name="seo_issues")
    op.drop_index("ix_seo_issues_tenant_id", table_name="seo_issues")
    op.drop_index("ix_seo_issues_project_id", table_name="seo_issues")
    op.drop_index("ix_seo_issues_crawl_page_id", table_name="seo_issues")
    op.drop_index("ix_seo_issues_crawl_job_id", table_name="seo_issues")
    op.drop_index("ix_seo_issues_audit_run_id", table_name="seo_issues")
    op.drop_table("seo_issues")

    op.drop_index("ix_seo_audit_runs_created", table_name="seo_audit_runs")
    op.drop_index("ix_seo_audit_runs_tenant_crawl", table_name="seo_audit_runs")
    op.drop_index("ix_seo_audit_runs_status", table_name="seo_audit_runs")
    op.drop_index("ix_seo_audit_runs_tenant_id", table_name="seo_audit_runs")
    op.drop_index("ix_seo_audit_runs_project_id", table_name="seo_audit_runs")
    op.drop_index("ix_seo_audit_runs_crawl_job_id", table_name="seo_audit_runs")
    op.drop_table("seo_audit_runs")

    issue_status.drop(op.get_bind(), checkfirst=True)
    issue_category.drop(op.get_bind(), checkfirst=True)
    issue_severity.drop(op.get_bind(), checkfirst=True)
    audit_status.drop(op.get_bind(), checkfirst=True)
