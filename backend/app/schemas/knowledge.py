"""Schemas for local knowledge base / RAG APIs."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge import KnowledgeSourceType


class KnowledgeSourceCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    source_type: KnowledgeSourceType = KnowledgeSourceType.manual_note
    description: Optional[str] = None
    project_id: Optional[UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    source_type: str
    title: str
    description: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class KnowledgeSourceListResponse(BaseModel):
    sources: List[KnowledgeSourceResponse]
    limit: int
    offset: int
    has_more: bool = False


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    source_id: UUID
    title: str
    raw_text: str
    normalized_text: str
    content_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_json")
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class KnowledgeDocumentListResponse(BaseModel):
    documents: List[KnowledgeDocumentResponse]
    limit: int
    offset: int
    has_more: bool = False


class KnowledgeIndexRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    source_id: UUID
    status: str
    progress: int = 0
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    qdrant_collection: str
    documents_processed: int = 0
    chunks_indexed: int = 0
    skipped_duplicates: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class KnowledgeSearchResult(BaseModel):
    point_id: str
    score: float
    tenant_id: str
    project_id: Optional[str] = None
    source_id: str
    document_id: str
    chunk_id: Optional[str] = None
    title: str
    source_type: str
    chunk_index: int
    text_preview: Optional[str] = None
    chunk_text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    query: str
    project_id: Optional[UUID] = None
    source_id: Optional[UUID] = None
    results: List[KnowledgeSearchResult]
    limit: int


class RelevantKnowledgeResponse(BaseModel):
    topic: str
    project_id: Optional[UUID] = None
    page_id: Optional[UUID] = None
    page_context: Optional[Dict[str, Any]] = None
    results: List[KnowledgeSearchResult]
    limit: int
