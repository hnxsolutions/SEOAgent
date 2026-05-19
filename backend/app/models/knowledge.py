"""Knowledge base models for local RAG foundations."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class KnowledgeSourceType(str, enum.Enum):
    manual_note = "manual_note"
    markdown = "markdown"
    text_file = "text_file"
    pdf = "pdf"
    docx = "docx"
    business_profile = "business_profile"
    case_study = "case_study"
    research = "research"


class KnowledgeSourceStatus(str, enum.Enum):
    active = "active"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"
    archived = "archived"


class KnowledgeDocumentStatus(str, enum.Enum):
    active = "active"
    indexed = "indexed"
    failed = "failed"
    archived = "archived"


class KnowledgeIndexRunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class KnowledgeSource(Base):
    """A user-provided source of business or research knowledge."""

    __tablename__ = "knowledge_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)

    source_type = Column(SQLEnum(KnowledgeSourceType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLEnum(KnowledgeSourceStatus), default=KnowledgeSourceStatus.active, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    documents = relationship("KnowledgeDocument", back_populates="source", cascade="all, delete-orphan")
    index_runs = relationship("KnowledgeIndexRun", back_populates="source")

    __table_args__ = (
        Index("ix_knowledge_sources_tenant_project", "tenant_id", "project_id"),
        Index("ix_knowledge_sources_created", "created_at", postgresql_using="brin"),
    )


class KnowledgeDocument(Base):
    """Normalized text document derived from a knowledge source."""

    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_sources.id"), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    raw_text = Column(Text, nullable=False)
    normalized_text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    status = Column(SQLEnum(KnowledgeDocumentStatus), default=KnowledgeDocumentStatus.active, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source = relationship("KnowledgeSource", back_populates="documents")
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_knowledge_documents_tenant_source", "tenant_id", "source_id"),
        Index("ix_knowledge_documents_dedupe", "tenant_id", "source_id", "content_hash", unique=True),
    )


class KnowledgeChunk(Base):
    """A vectorized chunk of user-provided knowledge."""

    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_documents.id"), nullable=False, index=True)

    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    text_preview = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=False, index=True)
    qdrant_point_id = Column(String(64), nullable=False, unique=True)
    metadata_json = Column("metadata", JSONB, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("KnowledgeDocument", back_populates="chunks")

    __table_args__ = (
        Index("ix_knowledge_chunks_tenant_project", "tenant_id", "project_id"),
        Index("ix_knowledge_chunks_document_index", "document_id", "chunk_index"),
        Index("ix_knowledge_chunks_dedupe", "tenant_id", "document_id", "chunk_index", "content_hash", unique=True),
    )


class KnowledgeIndexRun(Base):
    """A background-compatible indexing run for a knowledge source."""

    __tablename__ = "knowledge_index_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("knowledge_sources.id"), nullable=False, index=True)

    status = Column(
        SQLEnum(KnowledgeIndexRunStatus),
        default=KnowledgeIndexRunStatus.pending,
        nullable=False,
        index=True,
    )
    progress = Column(Integer, default=0)
    embedding_provider = Column(String(100), nullable=False)
    embedding_model = Column(String(255), nullable=False)
    embedding_dimension = Column(Integer, nullable=False)
    qdrant_collection = Column(String(255), nullable=False)

    documents_processed = Column(Integer, default=0)
    chunks_indexed = Column(Integer, default=0)
    skipped_duplicates = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source = relationship("KnowledgeSource", back_populates="index_runs")

    __table_args__ = (
        Index("ix_knowledge_index_runs_tenant_source", "tenant_id", "source_id"),
        Index("ix_knowledge_index_runs_created", "created_at", postgresql_using="brin"),
    )
