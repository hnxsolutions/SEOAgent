"""Add manual Search Console property onboarding fields.

Revision ID: 0013_gsc_manual_properties
Revises: 0012_weekly_seo_planner
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013_gsc_manual_properties"
down_revision: Union[str, None] = "0012_weekly_seo_planner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


property_source_type = postgresql.ENUM("oauth", "manual", name="gscpropertysourcetype", create_type=False)
property_type = postgresql.ENUM("domain", "url_prefix", name="gscpropertytype", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    property_source_type.create(bind, checkfirst=True)
    property_type.create(bind, checkfirst=True)

    op.add_column("gsc_properties", sa.Column("source_type", property_source_type, nullable=True))
    op.add_column("gsc_properties", sa.Column("property_type", property_type, nullable=True))
    op.add_column("gsc_properties", sa.Column("notes", sa.Text(), nullable=True))

    op.execute("UPDATE gsc_properties SET source_type = 'oauth'::gscpropertysourcetype WHERE source_type IS NULL")
    op.execute(
        "UPDATE gsc_properties SET property_type = CASE "
        "WHEN site_url LIKE 'sc-domain:%' THEN 'domain'::gscpropertytype "
        "ELSE 'url_prefix'::gscpropertytype END "
        "WHERE property_type IS NULL"
    )

    op.alter_column("gsc_properties", "source_type", nullable=False)
    op.alter_column("gsc_properties", "property_type", nullable=False)
    op.alter_column("gsc_properties", "connection_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column("gsc_sync_jobs", "connection_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    op.create_index("ix_gsc_properties_source_type", "gsc_properties", ["source_type"])
    op.create_index("ix_gsc_properties_property_type", "gsc_properties", ["property_type"])
    op.create_index(
        "ix_gsc_properties_manual_site",
        "gsc_properties",
        ["tenant_id", "project_id", "site_url", "source_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_gsc_properties_manual_site", table_name="gsc_properties")
    op.drop_index("ix_gsc_properties_property_type", table_name="gsc_properties")
    op.drop_index("ix_gsc_properties_source_type", table_name="gsc_properties")

    op.alter_column("gsc_sync_jobs", "connection_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.alter_column("gsc_properties", "connection_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("gsc_properties", "notes")
    op.drop_column("gsc_properties", "property_type")
    op.drop_column("gsc_properties", "source_type")

    property_type.drop(op.get_bind(), checkfirst=True)
    property_source_type.drop(op.get_bind(), checkfirst=True)
