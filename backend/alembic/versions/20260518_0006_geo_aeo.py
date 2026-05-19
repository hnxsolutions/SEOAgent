"""Add GEO/AEO scoring tables.

Revision ID: 0006_geo_aeo
Revises: 0005_content_optimization
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_geo_aeo"
down_revision: Union[str, None] = "0005_content_optimization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


run_status = postgresql.ENUM("pending", "running", "completed", "failed", name="geoaeorunstatus", create_type=False)
recommendation_type = postgresql.ENUM(
    "answer_block",
    "faq",
    "schema",
    "entity_clarity",
    "factual_claims",
    "trust_signal",
    "internal_link_support",
    "topical_gap",
    name="geoaeorecommendationtype",
    create_type=False,
)
recommendation_status = postgresql.ENUM(
    "suggested",
    "approved",
    "rejected",
    "applied",
    name="geoaeorecommendationstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    run_status.create(bind, checkfirst=True)
    recommendation_type.create(bind, checkfirst=True)
    recommendation_status.create(bind, checkfirst=True)

    op.create_table(
        "geo_aeo_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", run_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("total_recommendations", sa.Integer(), nullable=True),
        sa.Column("average_geo_score", sa.Float(), nullable=True),
        sa.Column("average_aeo_score", sa.Float(), nullable=True),
        sa.Column("average_citation_readiness_score", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_aeo_runs_crawl_id", "geo_aeo_runs", ["crawl_id"])
    op.create_index("ix_geo_aeo_runs_project_id", "geo_aeo_runs", ["project_id"])
    op.create_index("ix_geo_aeo_runs_tenant_id", "geo_aeo_runs", ["tenant_id"])
    op.create_index("ix_geo_aeo_runs_status", "geo_aeo_runs", ["status"])
    op.create_index("ix_geo_aeo_runs_created_at", "geo_aeo_runs", ["created_at"])
    op.create_index("ix_geo_aeo_runs_tenant_crawl", "geo_aeo_runs", ["tenant_id", "crawl_id"])
    op.create_index("ix_geo_aeo_runs_created", "geo_aeo_runs", ["created_at"], postgresql_using="brin")

    op.create_table(
        "geo_aeo_page_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("geo_score", sa.Float(), nullable=False),
        sa.Column("aeo_score", sa.Float(), nullable=False),
        sa.Column("citation_readiness_score", sa.Float(), nullable=False),
        sa.Column("answer_block_score", sa.Float(), nullable=False),
        sa.Column("entity_clarity_score", sa.Float(), nullable=False),
        sa.Column("schema_readiness_score", sa.Float(), nullable=False),
        sa.Column("trust_signal_score", sa.Float(), nullable=False),
        sa.Column("topical_completeness_score", sa.Float(), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extracted_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extracted_claims", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["geo_aeo_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_aeo_page_scores_run_id", "geo_aeo_page_scores", ["run_id"])
    op.create_index("ix_geo_aeo_page_scores_tenant_id", "geo_aeo_page_scores", ["tenant_id"])
    op.create_index("ix_geo_aeo_page_scores_project_id", "geo_aeo_page_scores", ["project_id"])
    op.create_index("ix_geo_aeo_page_scores_crawl_id", "geo_aeo_page_scores", ["crawl_id"])
    op.create_index("ix_geo_aeo_page_scores_page_id", "geo_aeo_page_scores", ["page_id"])
    op.create_index("ix_geo_aeo_page_scores_created_at", "geo_aeo_page_scores", ["created_at"])
    op.create_index("ix_geo_aeo_page_scores_run_page", "geo_aeo_page_scores", ["run_id", "page_id"], unique=True)
    op.create_index("ix_geo_aeo_page_scores_tenant_crawl", "geo_aeo_page_scores", ["tenant_id", "crawl_id"])
    op.create_index("ix_geo_aeo_page_scores_geo", "geo_aeo_page_scores", ["geo_score"])
    op.create_index("ix_geo_aeo_page_scores_aeo", "geo_aeo_page_scores", ["aeo_score"])

    op.create_table(
        "geo_aeo_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_type", recommendation_type, nullable=False),
        sa.Column("recommendation_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("status", recommendation_status, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["geo_aeo_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_geo_aeo_recommendations_run_id", "geo_aeo_recommendations", ["run_id"])
    op.create_index("ix_geo_aeo_recommendations_tenant_id", "geo_aeo_recommendations", ["tenant_id"])
    op.create_index("ix_geo_aeo_recommendations_project_id", "geo_aeo_recommendations", ["project_id"])
    op.create_index("ix_geo_aeo_recommendations_crawl_id", "geo_aeo_recommendations", ["crawl_id"])
    op.create_index("ix_geo_aeo_recommendations_page_id", "geo_aeo_recommendations", ["page_id"])
    op.create_index("ix_geo_aeo_recommendations_recommendation_type", "geo_aeo_recommendations", ["recommendation_type"])
    op.create_index("ix_geo_aeo_recommendations_status", "geo_aeo_recommendations", ["status"])
    op.create_index("ix_geo_aeo_recommendations_content_hash", "geo_aeo_recommendations", ["content_hash"])
    op.create_index("ix_geo_aeo_recommendations_created_at", "geo_aeo_recommendations", ["created_at"])
    op.create_index("ix_geo_aeo_recs_tenant_crawl", "geo_aeo_recommendations", ["tenant_id", "crawl_id"])
    op.create_index("ix_geo_aeo_recs_page_type", "geo_aeo_recommendations", ["page_id", "recommendation_type"])
    op.create_index(
        "ix_geo_aeo_recs_dedupe",
        "geo_aeo_recommendations",
        ["tenant_id", "crawl_id", "page_id", "recommendation_type", "content_hash"],
        unique=True,
    )
    op.create_index("ix_geo_aeo_recs_priority", "geo_aeo_recommendations", ["priority_score"])


def downgrade() -> None:
    op.drop_index("ix_geo_aeo_recs_priority", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recs_dedupe", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recs_page_type", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recs_tenant_crawl", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_created_at", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_content_hash", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_status", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_recommendation_type", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_page_id", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_crawl_id", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_project_id", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_tenant_id", table_name="geo_aeo_recommendations")
    op.drop_index("ix_geo_aeo_recommendations_run_id", table_name="geo_aeo_recommendations")
    op.drop_table("geo_aeo_recommendations")

    op.drop_index("ix_geo_aeo_page_scores_aeo", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_geo", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_tenant_crawl", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_run_page", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_created_at", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_page_id", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_crawl_id", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_project_id", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_tenant_id", table_name="geo_aeo_page_scores")
    op.drop_index("ix_geo_aeo_page_scores_run_id", table_name="geo_aeo_page_scores")
    op.drop_table("geo_aeo_page_scores")

    op.drop_index("ix_geo_aeo_runs_created", table_name="geo_aeo_runs")
    op.drop_index("ix_geo_aeo_runs_tenant_crawl", table_name="geo_aeo_runs")
    op.drop_index("ix_geo_aeo_runs_created_at", table_name="geo_aeo_runs")
    op.drop_index("ix_geo_aeo_runs_status", table_name="geo_aeo_runs")
    op.drop_index("ix_geo_aeo_runs_tenant_id", table_name="geo_aeo_runs")
    op.drop_index("ix_geo_aeo_runs_project_id", table_name="geo_aeo_runs")
    op.drop_index("ix_geo_aeo_runs_crawl_id", table_name="geo_aeo_runs")
    op.drop_table("geo_aeo_runs")

    recommendation_status.drop(op.get_bind(), checkfirst=True)
    recommendation_type.drop(op.get_bind(), checkfirst=True)
    run_status.drop(op.get_bind(), checkfirst=True)
