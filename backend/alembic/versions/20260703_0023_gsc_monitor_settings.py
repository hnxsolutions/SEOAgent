"""Add GSC project monitor settings.

Revision ID: 0023_gsc_monitor_settings
Revises: 0022_manual_keyword_baselines
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0023_gsc_monitor_settings"
down_revision: Union[str, None] = "0022_manual_keyword_baselines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gsc_project_monitor_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("frequency_days", sa.Integer(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("sync_queries", sa.Boolean(), nullable=False),
        sa.Column("sync_pages", sa.Boolean(), nullable=False),
        sa.Column("sync_query_page_pairs", sa.Boolean(), nullable=False),
        sa.Column("sync_country_device", sa.Boolean(), nullable=False),
        sa.Column("last_scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["property_id"], ["gsc_properties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gsc_monitor_tenant_project",
        "gsc_project_monitor_settings",
        ["tenant_id", "project_id"],
        unique=True,
    )
    op.create_index(
        "ix_gsc_monitor_due",
        "gsc_project_monitor_settings",
        ["enabled", "next_sync_at"],
    )
    op.create_index(
        "ix_gsc_monitor_project_property",
        "gsc_project_monitor_settings",
        ["project_id", "property_id"],
    )
    for name, column in {
        "ix_gsc_project_monitor_settings_tenant_id": "tenant_id",
        "ix_gsc_project_monitor_settings_project_id": "project_id",
        "ix_gsc_project_monitor_settings_property_id": "property_id",
        "ix_gsc_project_monitor_settings_enabled": "enabled",
        "ix_gsc_project_monitor_settings_last_scheduled_at": "last_scheduled_at",
        "ix_gsc_project_monitor_settings_next_sync_at": "next_sync_at",
        "ix_gsc_project_monitor_settings_created_at": "created_at",
    }.items():
        op.create_index(name, "gsc_project_monitor_settings", [column])


def downgrade() -> None:
    for name in [
        "ix_gsc_project_monitor_settings_created_at",
        "ix_gsc_project_monitor_settings_next_sync_at",
        "ix_gsc_project_monitor_settings_last_scheduled_at",
        "ix_gsc_project_monitor_settings_enabled",
        "ix_gsc_project_monitor_settings_property_id",
        "ix_gsc_project_monitor_settings_project_id",
        "ix_gsc_project_monitor_settings_tenant_id",
        "ix_gsc_monitor_project_property",
        "ix_gsc_monitor_due",
        "ix_gsc_monitor_tenant_project",
    ]:
        op.drop_index(name, table_name="gsc_project_monitor_settings")
    op.drop_table("gsc_project_monitor_settings")
