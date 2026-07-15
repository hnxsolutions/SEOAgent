"""Robots.txt intelligence tables.

Creates robots_analysis_runs and robots_issues for Phase 5 (Robots.txt
Intelligence). Only the robots tables are created here; unrelated index drift
reported by autogenerate is intentionally excluded.

Revision ID: 0026_robots_intelligence
Revises: 0025_planner_task_code_source
Create Date: 2026-07-15
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0026_robots_intelligence"
down_revision: Union[str, None] = "0025_planner_task_code_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "robots_analysis_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("robots_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.Enum("completed", "unreachable", "missing", name="robotsanalysisstatus"), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("sitemap_directive_count", sa.Integer(), nullable=False),
        sa.Column("user_agent_group_count", sa.Integer(), nullable=False),
        sa.Column("issues_found", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_robots_analysis_runs_content_hash"), "robots_analysis_runs", ["content_hash"], unique=False)
    op.create_index(op.f("ix_robots_analysis_runs_created_at"), "robots_analysis_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_robots_analysis_runs_project_id"), "robots_analysis_runs", ["project_id"], unique=False)
    op.create_index(op.f("ix_robots_analysis_runs_status"), "robots_analysis_runs", ["status"], unique=False)
    op.create_index(op.f("ix_robots_analysis_runs_tenant_id"), "robots_analysis_runs", ["tenant_id"], unique=False)
    op.create_index("ix_robots_runs_project_created", "robots_analysis_runs", ["project_id", "created_at"], unique=False)

    op.create_table(
        "robots_issues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("analysis_run_id", sa.UUID(), nullable=False),
        sa.Column(
            "issue_type",
            sa.Enum(
                "missing_robots", "unreachable_robots", "missing_sitemap_directive", "disallow_all",
                "blocked_css", "blocked_js", "blocked_images", "broken_wildcard",
                "conflicting_directives", "duplicate_directive", "crawl_trap", "invalid_directive",
                "sitemap_not_https", name="robotsissuetype",
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.Enum("low", "medium", "high", "critical", name="robotsissueseverity"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Enum("open", "approved", "fixed", "ignored", name="robotsissuestatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["robots_analysis_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_robots_issues_analysis_run_id"), "robots_issues", ["analysis_run_id"], unique=False)
    op.create_index(op.f("ix_robots_issues_created_at"), "robots_issues", ["created_at"], unique=False)
    op.create_index(op.f("ix_robots_issues_issue_type"), "robots_issues", ["issue_type"], unique=False)
    op.create_index(op.f("ix_robots_issues_project_id"), "robots_issues", ["project_id"], unique=False)
    op.create_index("ix_robots_issues_project_status", "robots_issues", ["project_id", "status"], unique=False)
    op.create_index(op.f("ix_robots_issues_severity"), "robots_issues", ["severity"], unique=False)
    op.create_index(op.f("ix_robots_issues_status"), "robots_issues", ["status"], unique=False)
    op.create_index(op.f("ix_robots_issues_tenant_id"), "robots_issues", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("robots_issues")
    op.drop_table("robots_analysis_runs")
    sa.Enum(name="robotsissuestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="robotsissueseverity").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="robotsissuetype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="robotsanalysisstatus").drop(op.get_bind(), checkfirst=True)
