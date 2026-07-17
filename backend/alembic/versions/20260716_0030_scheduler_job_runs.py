"""Scheduler / worker telemetry job runs.

Revision ID: 0030_scheduler_job_runs
Revises: 0029_briefings_notifications
Create Date: 2026-07-16
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0030_scheduler_job_runs"
down_revision: Union[str, None] = "0029_briefings_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_job_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("seo_run_id", sa.UUID(), nullable=True),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("trigger_type", sa.Enum("manual", "automatic", name="jobtriggertype"), nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", "retrying", "cancelled", name="jobstatus"),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cpu_time", sa.Float(), nullable=True),
        sa.Column("memory_usage", sa.Float(), nullable=True),
        sa.Column("next_run", sa.DateTime(), nullable=True),
        sa.Column("previous_run", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["seo_run_id"], ["seo_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "project_id", "seo_run_id", "job_name", "job_type",
                "trigger_type", "worker_name", "status", "started_at", "created_at"):
        op.create_index(op.f(f"ix_scheduler_job_runs_{col}"), "scheduler_job_runs", [col], unique=False)
    op.create_index("ix_scheduler_job_runs_name_status", "scheduler_job_runs", ["job_name", "status"], unique=False)
    op.create_index("ix_scheduler_job_runs_project_status", "scheduler_job_runs", ["project_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("scheduler_job_runs")
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="jobtriggertype").drop(op.get_bind(), checkfirst=True)
