"""Per-stage pipeline telemetry.

Revision ID: 0031_pipeline_stage_runs
Revises: 0030_scheduler_job_runs
Create Date: 2026-07-17
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0031_pipeline_stage_runs"
down_revision: Union[str, None] = "0030_scheduler_job_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_stage_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("seo_run_id", sa.UUID(), nullable=True),
        sa.Column("stage_name", sa.String(length=64), nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=True),
        # Reuse the existing jobstatus enum (created by migration 0030).
        sa.Column(
            "status",
            postgresql.ENUM("queued", "running", "completed", "failed", "retrying", "cancelled",
                            name="jobstatus", create_type=False),
            nullable=False,
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cpu_time", sa.Float(), nullable=True),
        sa.Column("memory_usage", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("logs", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["seo_run_id"], ["seo_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seo_run_id", "stage_name", name="uq_pipeline_stage_run"),
    )
    for col in ("tenant_id", "project_id", "seo_run_id", "stage_name", "status", "created_at", "updated_at"):
        op.create_index(op.f(f"ix_pipeline_stage_runs_{col}"), "pipeline_stage_runs", [col], unique=False)
    op.create_index("ix_pipeline_stage_runs_run_stage", "pipeline_stage_runs", ["seo_run_id", "stage_name"], unique=False)
    op.create_index("ix_pipeline_stage_runs_stage_status", "pipeline_stage_runs", ["stage_name", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("pipeline_stage_runs")
