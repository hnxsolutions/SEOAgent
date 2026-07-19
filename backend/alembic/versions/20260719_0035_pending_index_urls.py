"""Auto Index Queue (pending_index_urls).

Revision ID: 0035_pending_index_urls
Revises: 0034_site_validations
Create Date: 2026-07-19
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0035_pending_index_urls"
down_revision: Union[str, None] = "0034_site_validations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_index_urls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("source", sa.Enum("crawl", "blog", "planner", "sitemap", "manual", name="indexurlsource"), nullable=False),
        sa.Column("status", sa.Enum("pending", "approved", "rejected", "scheduled", "submitted", "indexed", name="indexurlstatus"), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("submitted_via", sa.String(length=32), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "url", name="uq_pending_index_project_url"),
    )
    for col in ("tenant_id", "project_id", "url", "source", "status", "eligible", "discovered_at", "created_at"):
        op.create_index(op.f(f"ix_pending_index_urls_{col}"), "pending_index_urls", [col], unique=False)
    op.create_index("ix_pending_index_project_status", "pending_index_urls", ["project_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("pending_index_urls")
    sa.Enum(name="indexurlstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="indexurlsource").drop(op.get_bind(), checkfirst=True)
