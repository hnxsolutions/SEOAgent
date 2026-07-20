"""Technology Fingerprint (technology_fingerprints).

Revision ID: 0036_technology_fingerprint
Revises: 0035_pending_index_urls
Create Date: 2026-07-20
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0036_technology_fingerprint"
down_revision: Union[str, None] = "0035_pending_index_urls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technology_fingerprints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Enum("url", "repo", "hybrid", name="fingerprintsource"), nullable=False),
        sa.Column("status", sa.Enum("detecting", "complete", "failed", name="fingerprintstatus"), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("technologies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("primary_framework", sa.String(length=255), nullable=True),
        sa.Column("primary_cms", sa.String(length=255), nullable=True),
        sa.Column("primary_language", sa.String(length=255), nullable=True),
        sa.Column("rendering", sa.String(length=255), nullable=True),
        sa.Column("hosting", sa.String(length=255), nullable=True),
        sa.Column("cdn", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_technology_fingerprint_project"),
    )
    for col in ("tenant_id", "project_id", "status", "content_hash"):
        op.create_index(op.f(f"ix_technology_fingerprints_{col}"), "technology_fingerprints", [col], unique=False)


def downgrade() -> None:
    op.drop_table("technology_fingerprints")
    sa.Enum(name="fingerprintstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="fingerprintsource").drop(op.get_bind(), checkfirst=True)
