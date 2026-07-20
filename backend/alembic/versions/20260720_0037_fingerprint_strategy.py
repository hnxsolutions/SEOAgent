"""Framework strategy fields on technology_fingerprints.

Revision ID: 0037_fingerprint_strategy
Revises: 0036_technology_fingerprint
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0037_fingerprint_strategy"
down_revision: Union[str, None] = "0036_technology_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("technology_fingerprints", sa.Column("strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("technology_fingerprints", sa.Column("secondary_framework", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("technology_fingerprints", "secondary_framework")
    op.drop_column("technology_fingerprints", "strategy")
