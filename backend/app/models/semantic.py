"""Models for local semantic SEO indexing."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class SemanticIndexStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class SemanticContentType(str, enum.Enum):
    full_text = "full_text"
    title = "title"
    meta_description = "meta_description"
    heading = "heading"
    chunk = "chunk"


class SemanticIndexRun(Base):
    """Semantic indexing job metadata for a crawl."""

    __tablename__ = "semantic_index_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    status = Column(SQLEnum(SemanticIndexStatus), default=SemanticIndexStatus.pending, nullable=False, index=True)
    progress = Column(Integer, default=0)
    embedding_provider = Column(String(100), nullable=False)
    embedding_model = Column(String(255), nullable=False)
    embedding_dimension = Column(Integer, nullable=False)
    qdrant_collection = Column(String(255), nullable=False)

    total_pages = Column(Integer, default=0)
    total_vectors = Column(Integer, default=0)
    indexed_vectors = Column(Integer, default=0)
    skipped_duplicates = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    indexed_contents = relationship("SemanticIndexedContent", back_populates="index_run")

    __table_args__ = (
        Index("ix_semantic_index_runs_tenant_crawl", "tenant_id", "crawl_job_id"),
        Index("ix_semantic_index_runs_created", "created_at", postgresql_using="brin"),
    )


class SemanticIndexedContent(Base):
    """A vectorized content unit stored in Qdrant."""

    __tablename__ = "semantic_indexed_contents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_run_id = Column(UUID(as_uuid=True), ForeignKey("semantic_index_runs.id"), nullable=False, index=True)
    crawl_job_id = Column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id"), nullable=False, index=True)
    crawl_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    content_type = Column(SQLEnum(SemanticContentType), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    embedding_model = Column(String(255), nullable=False, index=True)
    embedding_dimension = Column(Integer, nullable=False)
    qdrant_collection = Column(String(255), nullable=False)
    qdrant_point_id = Column(String(64), nullable=False, unique=True)

    url = Column(String(2048), nullable=False)
    heading_context = Column(String(500), nullable=True)
    chunk_index = Column(Integer, default=0)
    text_preview = Column(Text, nullable=True)

    indexed_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    index_run = relationship("SemanticIndexRun", back_populates="indexed_contents")

    __table_args__ = (
        Index(
            "ix_semantic_content_dedupe",
            "tenant_id",
            "crawl_job_id",
            "crawl_page_id",
            "embedding_model",
            "content_type",
            "chunk_index",
            "content_hash",
            unique=True,
        ),
        Index("ix_semantic_content_tenant_project", "tenant_id", "project_id"),
        Index("ix_semantic_content_page_model", "crawl_page_id", "embedding_model"),
    )
