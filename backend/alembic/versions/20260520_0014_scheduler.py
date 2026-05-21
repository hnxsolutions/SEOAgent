"""Add production SEO scheduler tables.

Revision ID: 0014_seo_scheduler
Revises: 0013_gsc_manual_properties
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_seo_scheduler"
down_revision: Union[str, None] = "0013_gsc_manual_properties"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


schedule_type = postgresql.ENUM(
    "daily_gsc_sync",
    "weekly_full_seo",
    "weekly_blog_planning",
    "weekly_repo_scan",
    "monthly_deep_audit",
    name="seoscheduletype",
    create_type=False,
)
schedule_frequency = postgresql.ENUM("daily", "weekly", "monthly", name="seoschedulefrequency", create_type=False)
scheduled_run_status = postgresql.ENUM(
    "queued",
    "running",
    "completed",
    "failed",
    "skipped",
    name="seoscheduledrunstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    schedule_type.create(bind, checkfirst=True)
    schedule_frequency.create(bind, checkfirst=True)
    scheduled_run_status.create(bind, checkfirst=True)

    op.create_table(
        "seo_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("schedule_type", schedule_type, nullable=False),
        sa.Column("frequency", schedule_frequency, nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    for column in [
        "tenant_id",
        "project_id",
        "schedule_type",
        "frequency",
        "is_enabled",
        "last_run_at",
        "next_run_at",
        "created_at",
    ]:
        op.create_index(f"ix_seo_schedules_{column}", "seo_schedules", [column])
    op.create_index("ix_seo_schedules_tenant_project", "seo_schedules", ["tenant_id", "project_id"])
    op.create_index("ix_seo_schedules_due", "seo_schedules", ["is_enabled", "next_run_at"])

    op.create_table(
        "seo_scheduled_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", scheduled_run_status, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("planner_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("gsc_sync_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("semantic_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_scan_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blog_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["audit_id"], ["seo_audit_runs.id"]),
        sa.ForeignKeyConstraint(["blog_plan_id"], ["blog_plans.id"]),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["gsc_sync_job_id"], ["gsc_sync_jobs.id"]),
        sa.ForeignKeyConstraint(["planner_run_id"], ["seo_planner_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_scan_run_id"], ["repo_scan_runs.id"]),
        sa.ForeignKeyConstraint(["schedule_id"], ["seo_schedules.id"]),
        sa.ForeignKeyConstraint(["semantic_run_id"], ["semantic_index_runs.id"]),
    )
    for column in [
        "tenant_id",
        "project_id",
        "schedule_id",
        "status",
        "planner_run_id",
        "gsc_sync_job_id",
        "crawl_id",
        "audit_id",
        "semantic_run_id",
        "repo_scan_run_id",
        "blog_plan_id",
        "created_at",
    ]:
        op.create_index(f"ix_seo_scheduled_runs_{column}", "seo_scheduled_runs", [column])
    op.create_index("ix_seo_scheduled_runs_tenant_project", "seo_scheduled_runs", ["tenant_id", "project_id"])
    op.create_index("ix_seo_scheduled_runs_schedule_status", "seo_scheduled_runs", ["schedule_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_seo_scheduled_runs_schedule_status", table_name="seo_scheduled_runs")
    op.drop_index("ix_seo_scheduled_runs_tenant_project", table_name="seo_scheduled_runs")
    for column in [
        "created_at",
        "blog_plan_id",
        "repo_scan_run_id",
        "semantic_run_id",
        "audit_id",
        "crawl_id",
        "gsc_sync_job_id",
        "planner_run_id",
        "status",
        "schedule_id",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_seo_scheduled_runs_{column}", table_name="seo_scheduled_runs")
    op.drop_table("seo_scheduled_runs")

    op.drop_index("ix_seo_schedules_due", table_name="seo_schedules")
    op.drop_index("ix_seo_schedules_tenant_project", table_name="seo_schedules")
    for column in [
        "created_at",
        "next_run_at",
        "last_run_at",
        "is_enabled",
        "frequency",
        "schedule_type",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_seo_schedules_{column}", table_name="seo_schedules")
    op.drop_table("seo_schedules")

    scheduled_run_status.drop(op.get_bind(), checkfirst=True)
    schedule_frequency.drop(op.get_bind(), checkfirst=True)
    schedule_type.drop(op.get_bind(), checkfirst=True)
