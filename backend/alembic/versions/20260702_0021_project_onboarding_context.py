"""Add project onboarding context fields.

Revision ID: 0021_project_onboarding_context
Revises: 0020_one_click_seo_runs
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021_project_onboarding_context"
down_revision: Union[str, None] = "0020_one_click_seo_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("business_name", sa.String(length=255), nullable=True))
    op.add_column("projects", sa.Column("industry", sa.String(length=255), nullable=True))
    op.add_column("projects", sa.Column("target_location", sa.String(length=255), nullable=True))
    op.add_column("projects", sa.Column("target_audience", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("primary_services", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("projects", sa.Column("target_keywords", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("projects", sa.Column("competitor_urls", postgresql.ARRAY(sa.String()), nullable=True))
    op.add_column("projects", sa.Column("seo_goal", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("brand_tone", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "brand_tone")
    op.drop_column("projects", "seo_goal")
    op.drop_column("projects", "competitor_urls")
    op.drop_column("projects", "target_keywords")
    op.drop_column("projects", "primary_services")
    op.drop_column("projects", "target_audience")
    op.drop_column("projects", "target_location")
    op.drop_column("projects", "industry")
    op.drop_column("projects", "business_name")
