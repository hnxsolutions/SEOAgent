"""Add local content optimization tables.

Revision ID: 0005_content_optimization
Revises: 0004_internal_links
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_content_optimization"
down_revision: Union[str, None] = "0004_internal_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


run_status = postgresql.ENUM(
    "pending", "running", "completed", "failed", name="contentoptimizationrunstatus", create_type=False
)
suggestion_type = postgresql.ENUM(
    "seo_title",
    "meta_description",
    "h1",
    "headings",
    "faq",
    "schema",
    "content_refresh",
    "answer_block",
    "internal_link_context",
    name="contentoptimizationsuggestiontype",
    create_type=False,
)
suggestion_status = postgresql.ENUM(
    "suggested",
    "approved",
    "rejected",
    "applied",
    name="contentoptimizationsuggestionstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    run_status.create(bind, checkfirst=True)
    suggestion_type.create(bind, checkfirst=True)
    suggestion_status.create(bind, checkfirst=True)

    op.create_table(
        "content_optimization_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("total_suggestions", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_optimization_runs_crawl_id", "content_optimization_runs", ["crawl_id"])
    op.create_index("ix_content_optimization_runs_project_id", "content_optimization_runs", ["project_id"])
    op.create_index("ix_content_optimization_runs_tenant_id", "content_optimization_runs", ["tenant_id"])
    op.create_index("ix_content_optimization_runs_status", "content_optimization_runs", ["status"])
    op.create_index("ix_content_optimization_runs_created_at", "content_optimization_runs", ["created_at"])
    op.create_index("ix_content_opt_runs_tenant_crawl", "content_optimization_runs", ["tenant_id", "crawl_id"])
    op.create_index("ix_content_opt_runs_created", "content_optimization_runs", ["created_at"], postgresql_using="brin")

    op.create_table(
        "content_optimization_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_type", suggestion_type, nullable=False),
        sa.Column("current_value", sa.Text(), nullable=True),
        sa.Column("suggested_value", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("status", suggestion_status, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["content_optimization_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_optimization_suggestions_run_id", "content_optimization_suggestions", ["run_id"])
    op.create_index("ix_content_optimization_suggestions_tenant_id", "content_optimization_suggestions", ["tenant_id"])
    op.create_index("ix_content_optimization_suggestions_project_id", "content_optimization_suggestions", ["project_id"])
    op.create_index("ix_content_optimization_suggestions_crawl_id", "content_optimization_suggestions", ["crawl_id"])
    op.create_index("ix_content_optimization_suggestions_page_id", "content_optimization_suggestions", ["page_id"])
    op.create_index("ix_content_optimization_suggestions_suggestion_type", "content_optimization_suggestions", ["suggestion_type"])
    op.create_index("ix_content_optimization_suggestions_status", "content_optimization_suggestions", ["status"])
    op.create_index("ix_content_optimization_suggestions_content_hash", "content_optimization_suggestions", ["content_hash"])
    op.create_index("ix_content_optimization_suggestions_created_at", "content_optimization_suggestions", ["created_at"])
    op.create_index("ix_content_opt_suggestions_tenant_crawl", "content_optimization_suggestions", ["tenant_id", "crawl_id"])
    op.create_index("ix_content_opt_suggestions_page_type", "content_optimization_suggestions", ["page_id", "suggestion_type"])
    op.create_index(
        "ix_content_opt_suggestions_dedupe",
        "content_optimization_suggestions",
        ["tenant_id", "crawl_id", "page_id", "suggestion_type", "content_hash"],
        unique=True,
    )
    op.create_index("ix_content_opt_suggestions_priority", "content_optimization_suggestions", ["priority_score"])


def downgrade() -> None:
    op.drop_index("ix_content_opt_suggestions_priority", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_opt_suggestions_dedupe", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_opt_suggestions_page_type", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_opt_suggestions_tenant_crawl", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_created_at", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_content_hash", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_status", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_suggestion_type", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_page_id", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_crawl_id", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_project_id", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_tenant_id", table_name="content_optimization_suggestions")
    op.drop_index("ix_content_optimization_suggestions_run_id", table_name="content_optimization_suggestions")
    op.drop_table("content_optimization_suggestions")

    op.drop_index("ix_content_opt_runs_created", table_name="content_optimization_runs")
    op.drop_index("ix_content_opt_runs_tenant_crawl", table_name="content_optimization_runs")
    op.drop_index("ix_content_optimization_runs_created_at", table_name="content_optimization_runs")
    op.drop_index("ix_content_optimization_runs_status", table_name="content_optimization_runs")
    op.drop_index("ix_content_optimization_runs_tenant_id", table_name="content_optimization_runs")
    op.drop_index("ix_content_optimization_runs_project_id", table_name="content_optimization_runs")
    op.drop_index("ix_content_optimization_runs_crawl_id", table_name="content_optimization_runs")
    op.drop_table("content_optimization_runs")

    suggestion_status.drop(op.get_bind(), checkfirst=True)
    suggestion_type.drop(op.get_bind(), checkfirst=True)
    run_status.drop(op.get_bind(), checkfirst=True)
