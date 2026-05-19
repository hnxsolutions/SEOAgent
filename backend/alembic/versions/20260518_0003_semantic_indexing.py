"""Add local semantic indexing tables.

Revision ID: 0003_semantic_indexing
Revises: 0002_seo_audit_tables
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_semantic_indexing"
down_revision: Union[str, None] = "0002_seo_audit_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


semantic_index_status = postgresql.ENUM(
    "pending", "running", "completed", "failed", name="semanticindexstatus", create_type=False
)
semantic_content_type = postgresql.ENUM(
    "full_text", "title", "meta_description", "heading", "chunk", name="semanticcontenttype", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    semantic_index_status.create(bind, checkfirst=True)
    semantic_content_type.create(bind, checkfirst=True)

    op.create_table(
        "semantic_index_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", semantic_index_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("embedding_provider", sa.String(length=100), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("qdrant_collection", sa.String(length=255), nullable=False),
        sa.Column("total_pages", sa.Integer(), nullable=True),
        sa.Column("total_vectors", sa.Integer(), nullable=True),
        sa.Column("indexed_vectors", sa.Integer(), nullable=True),
        sa.Column("skipped_duplicates", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_semantic_index_runs_crawl_job_id", "semantic_index_runs", ["crawl_job_id"])
    op.create_index("ix_semantic_index_runs_project_id", "semantic_index_runs", ["project_id"])
    op.create_index("ix_semantic_index_runs_tenant_id", "semantic_index_runs", ["tenant_id"])
    op.create_index("ix_semantic_index_runs_status", "semantic_index_runs", ["status"])
    op.create_index("ix_semantic_index_runs_tenant_crawl", "semantic_index_runs", ["tenant_id", "crawl_job_id"])
    op.create_index("ix_semantic_index_runs_created", "semantic_index_runs", ["created_at"], postgresql_using="brin")

    op.create_table(
        "semantic_indexed_contents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", semantic_content_type, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("qdrant_collection", sa.String(length=255), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("heading_context", sa.String(length=500), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("text_preview", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"]),
        sa.ForeignKeyConstraint(["index_run_id"], ["semantic_index_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qdrant_point_id"),
    )
    op.create_index("ix_semantic_indexed_contents_index_run_id", "semantic_indexed_contents", ["index_run_id"])
    op.create_index("ix_semantic_indexed_contents_crawl_job_id", "semantic_indexed_contents", ["crawl_job_id"])
    op.create_index("ix_semantic_indexed_contents_crawl_page_id", "semantic_indexed_contents", ["crawl_page_id"])
    op.create_index("ix_semantic_indexed_contents_project_id", "semantic_indexed_contents", ["project_id"])
    op.create_index("ix_semantic_indexed_contents_tenant_id", "semantic_indexed_contents", ["tenant_id"])
    op.create_index("ix_semantic_indexed_contents_content_type", "semantic_indexed_contents", ["content_type"])
    op.create_index("ix_semantic_indexed_contents_content_hash", "semantic_indexed_contents", ["content_hash"])
    op.create_index("ix_semantic_indexed_contents_embedding_model", "semantic_indexed_contents", ["embedding_model"])
    op.create_index("ix_semantic_indexed_contents_indexed_at", "semantic_indexed_contents", ["indexed_at"])
    op.create_index(
        "ix_semantic_content_dedupe",
        "semantic_indexed_contents",
        ["tenant_id", "crawl_job_id", "crawl_page_id", "embedding_model", "content_type", "chunk_index", "content_hash"],
        unique=True,
    )
    op.create_index(
        "ix_semantic_content_tenant_project",
        "semantic_indexed_contents",
        ["tenant_id", "project_id"],
    )
    op.create_index(
        "ix_semantic_content_page_model",
        "semantic_indexed_contents",
        ["crawl_page_id", "embedding_model"],
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_content_page_model", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_content_tenant_project", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_content_dedupe", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_indexed_at", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_embedding_model", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_content_hash", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_content_type", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_tenant_id", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_project_id", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_crawl_page_id", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_crawl_job_id", table_name="semantic_indexed_contents")
    op.drop_index("ix_semantic_indexed_contents_index_run_id", table_name="semantic_indexed_contents")
    op.drop_table("semantic_indexed_contents")

    op.drop_index("ix_semantic_index_runs_created", table_name="semantic_index_runs")
    op.drop_index("ix_semantic_index_runs_tenant_crawl", table_name="semantic_index_runs")
    op.drop_index("ix_semantic_index_runs_status", table_name="semantic_index_runs")
    op.drop_index("ix_semantic_index_runs_tenant_id", table_name="semantic_index_runs")
    op.drop_index("ix_semantic_index_runs_project_id", table_name="semantic_index_runs")
    op.drop_index("ix_semantic_index_runs_crawl_job_id", table_name="semantic_index_runs")
    op.drop_table("semantic_index_runs")

    semantic_content_type.drop(op.get_bind(), checkfirst=True)
    semantic_index_status.drop(op.get_bind(), checkfirst=True)
