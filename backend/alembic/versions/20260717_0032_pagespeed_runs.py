"""Core Web Vitals / PageSpeed runs.

Revision ID: 0032_pagespeed_runs
Revises: 0031_pipeline_stage_runs
Create Date: 2026-07-17
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0032_pagespeed_runs"
down_revision: Union[str, None] = "0031_pipeline_stage_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pagespeed_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("strategy", sa.Enum("mobile", "desktop", name="pagespeedstrategy"), nullable=False),
        sa.Column("status", sa.Enum("completed", "quota_exceeded", "error", name="pagespeedstatus"), nullable=False),
        sa.Column("performance_score", sa.Float(), nullable=True),
        sa.Column("accessibility_score", sa.Float(), nullable=True),
        sa.Column("best_practices_score", sa.Float(), nullable=True),
        sa.Column("seo_score", sa.Float(), nullable=True),
        sa.Column("lcp_ms", sa.Float(), nullable=True),
        sa.Column("cls", sa.Float(), nullable=True),
        sa.Column("inp_ms", sa.Float(), nullable=True),
        sa.Column("tbt_ms", sa.Float(), nullable=True),
        sa.Column("fcp_ms", sa.Float(), nullable=True),
        sa.Column("speed_index_ms", sa.Float(), nullable=True),
        sa.Column("ttfb_ms", sa.Float(), nullable=True),
        sa.Column("field_lcp_ms", sa.Float(), nullable=True),
        sa.Column("field_cls", sa.Float(), nullable=True),
        sa.Column("field_inp_ms", sa.Float(), nullable=True),
        sa.Column("opportunities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pagespeed_runs_tenant_id"), "pagespeed_runs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_pagespeed_runs_project_id"), "pagespeed_runs", ["project_id"], unique=False)
    op.create_index(op.f("ix_pagespeed_runs_strategy"), "pagespeed_runs", ["strategy"], unique=False)
    op.create_index(op.f("ix_pagespeed_runs_status"), "pagespeed_runs", ["status"], unique=False)
    op.create_index(op.f("ix_pagespeed_runs_created_at"), "pagespeed_runs", ["created_at"], unique=False)
    op.create_index("ix_pagespeed_runs_project_strategy", "pagespeed_runs", ["project_id", "strategy"], unique=False)
    op.create_index("ix_pagespeed_runs_project_created", "pagespeed_runs", ["project_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("pagespeed_runs")
    sa.Enum(name="pagespeedstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="pagespeedstrategy").drop(op.get_bind(), checkfirst=True)
