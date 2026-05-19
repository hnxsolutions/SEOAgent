"""Add knowledge base RAG tables.

Revision ID: 0007_knowledge_base
Revises: 0006_geo_aeo
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007_knowledge_base"
down_revision: Union[str, None] = "0006_geo_aeo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


source_type = postgresql.ENUM(
    "manual_note",
    "markdown",
    "text_file",
    "pdf",
    "docx",
    "business_profile",
    "case_study",
    "research",
    name="knowledgesourcetype",
    create_type=False,
)
source_status = postgresql.ENUM(
    "active",
    "indexing",
    "indexed",
    "failed",
    "archived",
    name="knowledgesourcestatus",
    create_type=False,
)
document_status = postgresql.ENUM(
    "active",
    "indexed",
    "failed",
    "archived",
    name="knowledgedocumentstatus",
    create_type=False,
)
index_run_status = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    name="knowledgeindexrunstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    source_type.create(bind, checkfirst=True)
    source_status.create(bind, checkfirst=True)
    document_status.create(bind, checkfirst=True)
    index_run_status.create(bind, checkfirst=True)

    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", source_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_sources_tenant_id", "knowledge_sources", ["tenant_id"])
    op.create_index("ix_knowledge_sources_project_id", "knowledge_sources", ["project_id"])
    op.create_index("ix_knowledge_sources_source_type", "knowledge_sources", ["source_type"])
    op.create_index("ix_knowledge_sources_status", "knowledge_sources", ["status"])
    op.create_index("ix_knowledge_sources_created_at", "knowledge_sources", ["created_at"])
    op.create_index("ix_knowledge_sources_tenant_project", "knowledge_sources", ["tenant_id", "project_id"])
    op.create_index("ix_knowledge_sources_created", "knowledge_sources", ["created_at"], postgresql_using="brin")

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", document_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])
    op.create_index("ix_knowledge_documents_project_id", "knowledge_documents", ["project_id"])
    op.create_index("ix_knowledge_documents_source_id", "knowledge_documents", ["source_id"])
    op.create_index("ix_knowledge_documents_content_hash", "knowledge_documents", ["content_hash"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_index("ix_knowledge_documents_created_at", "knowledge_documents", ["created_at"])
    op.create_index("ix_knowledge_documents_tenant_source", "knowledge_documents", ["tenant_id", "source_id"])
    op.create_index(
        "ix_knowledge_documents_dedupe",
        "knowledge_documents",
        ["tenant_id", "source_id", "content_hash"],
        unique=True,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("text_preview", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("qdrant_point_id", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qdrant_point_id"),
    )
    op.create_index("ix_knowledge_chunks_tenant_id", "knowledge_chunks", ["tenant_id"])
    op.create_index("ix_knowledge_chunks_project_id", "knowledge_chunks", ["project_id"])
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_content_hash", "knowledge_chunks", ["content_hash"])
    op.create_index("ix_knowledge_chunks_created_at", "knowledge_chunks", ["created_at"])
    op.create_index("ix_knowledge_chunks_tenant_project", "knowledge_chunks", ["tenant_id", "project_id"])
    op.create_index("ix_knowledge_chunks_document_index", "knowledge_chunks", ["document_id", "chunk_index"])
    op.create_index(
        "ix_knowledge_chunks_dedupe",
        "knowledge_chunks",
        ["tenant_id", "document_id", "chunk_index", "content_hash"],
        unique=True,
    )

    op.create_table(
        "knowledge_index_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", index_run_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("embedding_provider", sa.String(length=100), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("qdrant_collection", sa.String(length=255), nullable=False),
        sa.Column("documents_processed", sa.Integer(), nullable=True),
        sa.Column("chunks_indexed", sa.Integer(), nullable=True),
        sa.Column("skipped_duplicates", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_index_runs_tenant_id", "knowledge_index_runs", ["tenant_id"])
    op.create_index("ix_knowledge_index_runs_project_id", "knowledge_index_runs", ["project_id"])
    op.create_index("ix_knowledge_index_runs_source_id", "knowledge_index_runs", ["source_id"])
    op.create_index("ix_knowledge_index_runs_status", "knowledge_index_runs", ["status"])
    op.create_index("ix_knowledge_index_runs_created_at", "knowledge_index_runs", ["created_at"])
    op.create_index("ix_knowledge_index_runs_tenant_source", "knowledge_index_runs", ["tenant_id", "source_id"])
    op.create_index("ix_knowledge_index_runs_created", "knowledge_index_runs", ["created_at"], postgresql_using="brin")


def downgrade() -> None:
    op.drop_index("ix_knowledge_index_runs_created", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_tenant_source", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_created_at", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_status", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_source_id", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_project_id", table_name="knowledge_index_runs")
    op.drop_index("ix_knowledge_index_runs_tenant_id", table_name="knowledge_index_runs")
    op.drop_table("knowledge_index_runs")

    op.drop_index("ix_knowledge_chunks_dedupe", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document_index", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_tenant_project", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_created_at", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_project_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_tenant_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index("ix_knowledge_documents_dedupe", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_tenant_source", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_created_at", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_source_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_project_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_tenant_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")

    op.drop_index("ix_knowledge_sources_created", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_project", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_created_at", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_status", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_source_type", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_project_id", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_tenant_id", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")

    index_run_status.drop(op.get_bind(), checkfirst=True)
    document_status.drop(op.get_bind(), checkfirst=True)
    source_status.drop(op.get_bind(), checkfirst=True)
    source_type.drop(op.get_bind(), checkfirst=True)
