"""Add deterministic internal link recommendation table.

Revision ID: 0004_internal_links
Revises: 0003_semantic_indexing
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_internal_links"
down_revision: Union[str, None] = "0003_semantic_indexing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


recommendation_status = postgresql.ENUM(
    "suggested", "approved", "rejected", "applied", name="internallinkrecommendationstatus", create_type=False
)
recommendation_type = postgresql.ENUM(
    "semantic_related",
    "orphan_support",
    "weak_page_support",
    "hub_spoke",
    "audit_issue_support",
    name="internallinkrecommendationtype",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    recommendation_status.create(bind, checkfirst=True)
    recommendation_type.create(bind, checkfirst=True)

    op.create_table(
        "internal_link_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("target_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("suggested_anchor_text", sa.String(length=255), nullable=False),
        sa.Column("suggested_context_snippet", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("status", recommendation_status, nullable=False),
        sa.Column("recommendation_type", recommendation_type, nullable=False),
        sa.Column("semantic_similarity", sa.Float(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["target_page_id"], ["crawl_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internal_link_recommendations_crawl_job_id", "internal_link_recommendations", ["crawl_job_id"])
    op.create_index("ix_internal_link_recommendations_project_id", "internal_link_recommendations", ["project_id"])
    op.create_index("ix_internal_link_recommendations_tenant_id", "internal_link_recommendations", ["tenant_id"])
    op.create_index("ix_internal_link_recommendations_source_page_id", "internal_link_recommendations", ["source_page_id"])
    op.create_index("ix_internal_link_recommendations_target_page_id", "internal_link_recommendations", ["target_page_id"])
    op.create_index("ix_internal_link_recommendations_status", "internal_link_recommendations", ["status"])
    op.create_index("ix_internal_link_recommendations_recommendation_type", "internal_link_recommendations", ["recommendation_type"])
    op.create_index("ix_internal_link_recommendations_created_at", "internal_link_recommendations", ["created_at"])
    op.create_index("ix_internal_link_recs_tenant_crawl", "internal_link_recommendations", ["tenant_id", "crawl_job_id"])
    op.create_index("ix_internal_link_recs_source_target", "internal_link_recommendations", ["source_page_id", "target_page_id"])
    op.create_index(
        "ix_internal_link_recs_dedupe",
        "internal_link_recommendations",
        ["tenant_id", "crawl_job_id", "source_page_id", "target_page_id", "recommendation_type"],
        unique=True,
    )
    op.create_index("ix_internal_link_recs_priority", "internal_link_recommendations", ["priority_score"])


def downgrade() -> None:
    op.drop_index("ix_internal_link_recs_priority", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recs_dedupe", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recs_source_target", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recs_tenant_crawl", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_created_at", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_recommendation_type", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_status", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_target_page_id", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_source_page_id", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_tenant_id", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_project_id", table_name="internal_link_recommendations")
    op.drop_index("ix_internal_link_recommendations_crawl_job_id", table_name="internal_link_recommendations")
    op.drop_table("internal_link_recommendations")

    recommendation_type.drop(op.get_bind(), checkfirst=True)
    recommendation_status.drop(op.get_bind(), checkfirst=True)
