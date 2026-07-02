"""Add manual keyword baselines.

Revision ID: 0022_manual_keyword_baselines
Revises: 0021_project_onboarding_context
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022_manual_keyword_baselines"
down_revision: Union[str, None] = "0021_project_onboarding_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


keyword_baseline_device = postgresql.ENUM(
    "desktop",
    "mobile",
    name="keywordbaselinedevice",
    create_type=False,
)
keyword_baseline_source = postgresql.ENUM(
    "manual",
    "csv",
    "imported",
    name="keywordbaselinesource",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    keyword_baseline_device.create(bind, checkfirst=True)
    keyword_baseline_source.create(bind, checkfirst=True)

    op.create_table(
        "keyword_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword", sa.String(length=1000), nullable=False),
        sa.Column("target_location", sa.String(length=255), nullable=True),
        sa.Column("search_engine", sa.String(length=50), nullable=False),
        sa.Column("device", keyword_baseline_device, nullable=False),
        sa.Column("current_position", sa.Integer(), nullable=True),
        sa.Column("current_url", sa.String(length=2048), nullable=True),
        sa.Column("search_volume", sa.Integer(), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", keyword_baseline_source, nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_keyword_baselines_tenant_id": ["tenant_id"],
        "ix_keyword_baselines_project_id": ["project_id"],
        "ix_keyword_baselines_keyword": ["keyword"],
        "ix_keyword_baselines_target_location": ["target_location"],
        "ix_keyword_baselines_search_engine": ["search_engine"],
        "ix_keyword_baselines_device": ["device"],
        "ix_keyword_baselines_current_position": ["current_position"],
        "ix_keyword_baselines_intent": ["intent"],
        "ix_keyword_baselines_source": ["source"],
        "ix_keyword_baselines_captured_at": ["captured_at"],
        "ix_keyword_baselines_project_keyword_device_location": [
            "project_id",
            "keyword",
            "device",
            "target_location",
        ],
        "ix_keyword_baselines_tenant_project": ["tenant_id", "project_id"],
    }.items():
        op.create_index(name, "keyword_baselines", cols)


def downgrade() -> None:
    for name in [
        "ix_keyword_baselines_tenant_project",
        "ix_keyword_baselines_project_keyword_device_location",
        "ix_keyword_baselines_captured_at",
        "ix_keyword_baselines_source",
        "ix_keyword_baselines_intent",
        "ix_keyword_baselines_current_position",
        "ix_keyword_baselines_device",
        "ix_keyword_baselines_search_engine",
        "ix_keyword_baselines_target_location",
        "ix_keyword_baselines_keyword",
        "ix_keyword_baselines_project_id",
        "ix_keyword_baselines_tenant_id",
    ]:
        op.drop_index(name, table_name="keyword_baselines")
    op.drop_table("keyword_baselines")
    bind = op.get_bind()
    keyword_baseline_source.drop(bind, checkfirst=True)
    keyword_baseline_device.drop(bind, checkfirst=True)
