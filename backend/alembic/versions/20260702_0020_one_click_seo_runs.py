"""Add one-click SEO run table.

Revision ID: 0020_one_click_seo_runs
Revises: 0019_gsc_indexing_intelligence
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020_one_click_seo_runs"
down_revision: Union[str, None] = "0019_gsc_indexing_intelligence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


seo_run_status = postgresql.ENUM("queued", "running", "completed", "failed", name="seorunstatus", create_type=False)
seo_run_stage = postgresql.ENUM(
    "crawl",
    "audit",
    "semantic_index",
    "content_optimization",
    "planner",
    "completed",
    name="seorunstage",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    seo_run_status.create(bind, checkfirst=True)
    seo_run_stage.create(bind, checkfirst=True)

    op.create_table(
        "seo_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", seo_run_status, nullable=False),
        sa.Column("current_stage", seo_run_stage, nullable=False),
        sa.Column("stage_statuses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stage_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("semantic_index_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_optimization_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("planner_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["audit_id"], ["seo_audit_runs.id"]),
        sa.ForeignKeyConstraint(["content_optimization_run_id"], ["content_optimization_runs.id"]),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["planner_run_id"], ["seo_planner_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["semantic_index_run_id"], ["semantic_index_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in [
        "tenant_id",
        "project_id",
        "status",
        "current_stage",
        "crawl_id",
        "audit_id",
        "semantic_index_run_id",
        "content_optimization_run_id",
        "planner_run_id",
        "created_at",
    ]:
        op.create_index(f"ix_seo_runs_{column}", "seo_runs", [column])
    op.create_index("ix_seo_runs_tenant_project", "seo_runs", ["tenant_id", "project_id"])
    op.create_index("ix_seo_runs_status_created", "seo_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_seo_runs_status_created", table_name="seo_runs")
    op.drop_index("ix_seo_runs_tenant_project", table_name="seo_runs")
    for column in [
        "created_at",
        "planner_run_id",
        "content_optimization_run_id",
        "semantic_index_run_id",
        "audit_id",
        "crawl_id",
        "current_stage",
        "status",
        "project_id",
        "tenant_id",
    ]:
        op.drop_index(f"ix_seo_runs_{column}", table_name="seo_runs")
    op.drop_table("seo_runs")
    seo_run_stage.drop(op.get_bind(), checkfirst=True)
    seo_run_status.drop(op.get_bind(), checkfirst=True)
