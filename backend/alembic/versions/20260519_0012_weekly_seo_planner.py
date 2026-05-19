"""Add weekly autonomous SEO planner tables.

Revision ID: 0012_weekly_seo_planner
Revises: 0011_patch_apply_pr_layer
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0012_weekly_seo_planner"
down_revision: Union[str, None] = "0011_patch_apply_pr_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


planner_status = postgresql.ENUM("queued", "running", "completed", "failed", name="seoplannerrunstatus", create_type=False)
planner_run_type = postgresql.ENUM("manual", "scheduled", name="seoplannerruntype", create_type=False)
task_type = postgresql.ENUM(
    "technical_seo_fix",
    "metadata_rewrite",
    "schema_addition",
    "content_refresh",
    "internal_link",
    "blog_topic",
    "blog_draft",
    "geo_aeo_improvement",
    "search_console_opportunity",
    "repo_patch_review",
    "sitemap_robots_fix",
    "local_seo_task",
    "citation_task",
    "backlink_opportunity",
    "manual_review",
    name="seotasktype",
    create_type=False,
)
task_source = postgresql.ENUM(
    "audit_issue",
    "content_optimization",
    "geo_aeo",
    "search_console",
    "internal_linking",
    "blog_engine",
    "repo_agent",
    "planner",
    name="seotasksourcetype",
    create_type=False,
)
task_priority = postgresql.ENUM("low", "medium", "high", "critical", name="seotaskpriority", create_type=False)
task_impact = postgresql.ENUM("low", "medium", "high", name="seotaskimpact", create_type=False)
task_effort = postgresql.ENUM("low", "medium", "high", name="seotaskeffort", create_type=False)
task_status = postgresql.ENUM(
    "todo", "in_progress", "approved", "rejected", "completed", "skipped",
    name="seotaskstatus",
    create_type=False,
)
dependency_type = postgresql.ENUM("blocks", "related", "follow_up", name="seotaskdependencytype", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        planner_status,
        planner_run_type,
        task_type,
        task_source,
        task_priority,
        task_impact,
        task_effort,
        task_status,
        dependency_type,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "seo_planner_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", planner_status, nullable=False),
        sa.Column("run_type", planner_run_type, nullable=False),
        sa.Column("target_week_start", sa.DateTime(), nullable=False),
        sa.Column("target_week_end", sa.DateTime(), nullable=False),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("semantic_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("internal_link_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_optimization_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("geo_aeo_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("gsc_sync_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blog_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_scan_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tasks_created", sa.Integer(), nullable=True),
        sa.Column("high_priority_tasks", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["audit_id"], ["seo_audit_runs.id"]),
        sa.ForeignKeyConstraint(["blog_plan_id"], ["blog_plans.id"]),
        sa.ForeignKeyConstraint(["content_optimization_run_id"], ["content_optimization_runs.id"]),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["geo_aeo_run_id"], ["geo_aeo_runs.id"]),
        sa.ForeignKeyConstraint(["gsc_sync_job_id"], ["gsc_sync_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_scan_run_id"], ["repo_scan_runs.id"]),
        sa.ForeignKeyConstraint(["semantic_run_id"], ["semantic_index_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in [
        "tenant_id",
        "project_id",
        "status",
        "run_type",
        "target_week_start",
        "target_week_end",
        "crawl_id",
        "audit_id",
        "semantic_run_id",
        "internal_link_run_id",
        "content_optimization_run_id",
        "geo_aeo_run_id",
        "gsc_sync_job_id",
        "blog_plan_id",
        "repo_scan_run_id",
        "created_at",
    ]:
        op.create_index(f"ix_seo_planner_runs_{column}", "seo_planner_runs", [column])
    op.create_index("ix_seo_planner_runs_tenant_project", "seo_planner_runs", ["tenant_id", "project_id"])
    op.create_index("ix_seo_planner_runs_status_created", "seo_planner_runs", ["status", "created_at"])

    op.create_table(
        "seo_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planner_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_type", task_source, nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_page_url", sa.String(length=2048), nullable=True),
        sa.Column("target_keyword", sa.String(length=255), nullable=True),
        sa.Column("priority", task_priority, nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("estimated_impact", task_impact, nullable=False),
        sa.Column("effort", task_effort, nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["planner_run_id"], ["seo_planner_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in [
        "tenant_id",
        "project_id",
        "planner_run_id",
        "task_type",
        "source_type",
        "source_reference_id",
        "target_page_url",
        "target_keyword",
        "priority",
        "priority_score",
        "estimated_impact",
        "effort",
        "status",
        "due_date",
        "created_at",
    ]:
        op.create_index(f"ix_seo_tasks_{column}", "seo_tasks", [column])
    op.create_index("ix_seo_tasks_tenant_project", "seo_tasks", ["tenant_id", "project_id"])
    op.create_index("ix_seo_tasks_project_status_priority", "seo_tasks", ["project_id", "status", "priority_score"])
    op.create_index(
        "ix_seo_tasks_dedupe_lookup",
        "seo_tasks",
        ["tenant_id", "project_id", "task_type", "target_page_url", "target_keyword", "source_type", "source_reference_id", "status"],
    )

    op.create_table(
        "seo_task_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dependency_type", dependency_type, nullable=False),
        sa.ForeignKeyConstraint(["depends_on_task_id"], ["seo_tasks.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["seo_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_task_dependencies_tenant_id", "seo_task_dependencies", ["tenant_id"])
    op.create_index("ix_seo_task_dependencies_project_id", "seo_task_dependencies", ["project_id"])
    op.create_index("ix_seo_task_dependencies_task_id", "seo_task_dependencies", ["task_id"])
    op.create_index("ix_seo_task_dependencies_depends_on_task_id", "seo_task_dependencies", ["depends_on_task_id"])
    op.create_index("ix_seo_task_dependencies_dependency_type", "seo_task_dependencies", ["dependency_type"])
    op.create_index("ix_seo_task_deps_tenant_project", "seo_task_dependencies", ["tenant_id", "project_id"])
    op.create_index("ix_seo_task_deps_unique", "seo_task_dependencies", ["task_id", "depends_on_task_id", "dependency_type"], unique=True)

    op.create_table(
        "seo_weekly_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("planner_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("wins", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("technical_seo_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("search_console_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("geo_aeo_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("blog_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("repo_patch_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("next_week_priorities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["planner_run_id"], ["seo_planner_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_weekly_reports_tenant_id", "seo_weekly_reports", ["tenant_id"])
    op.create_index("ix_seo_weekly_reports_project_id", "seo_weekly_reports", ["project_id"])
    op.create_index("ix_seo_weekly_reports_planner_run_id", "seo_weekly_reports", ["planner_run_id"])
    op.create_index("ix_seo_weekly_reports_created_at", "seo_weekly_reports", ["created_at"])
    op.create_index("ix_seo_weekly_reports_tenant_project", "seo_weekly_reports", ["tenant_id", "project_id"])
    op.create_index("ix_seo_weekly_reports_run", "seo_weekly_reports", ["planner_run_id"], unique=True)


def downgrade() -> None:
    op.drop_table("seo_weekly_reports")
    op.drop_table("seo_task_dependencies")
    op.drop_table("seo_tasks")
    op.drop_table("seo_planner_runs")

    for enum_type in (
        dependency_type,
        task_status,
        task_effort,
        task_impact,
        task_priority,
        task_source,
        task_type,
        planner_run_type,
        planner_status,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
