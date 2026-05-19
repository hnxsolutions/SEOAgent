"""Pydantic schemas for local semantic SEO indexing."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SemanticIndexRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    crawl_job_id: UUID
    project_id: Optional[UUID] = None
    tenant_id: UUID
    status: str
    progress: int = 0
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    qdrant_collection: str
    total_pages: int = 0
    total_vectors: int = 0
    indexed_vectors: int = 0
    skipped_duplicates: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SemanticSearchResult(BaseModel):
    point_id: str
    score: float
    tenant_id: str
    project_id: Optional[str] = None
    crawl_id: str
    page_id: str
    url: str
    content_type: str
    heading_context: Optional[str] = None
    chunk_index: Optional[int] = None
    text_preview: Optional[str] = None


class SemanticSearchResponse(BaseModel):
    query: str
    results: List[SemanticSearchResult]
    limit: int


class SemanticSimilarPagesResponse(BaseModel):
    page_id: UUID
    results: List[SemanticSearchResult]
    limit: int


class SemanticClusterPage(BaseModel):
    page_id: str
    url: str
    score: float
    text_preview: Optional[str] = None


class SemanticCluster(BaseModel):
    cluster_id: int
    representative_url: Optional[str] = None
    representative_page_id: Optional[str] = None
    size: int
    pages: List[SemanticClusterPage] = Field(default_factory=list)


class SemanticClustersResponse(BaseModel):
    crawl_id: UUID
    clusters: List[SemanticCluster]
    limit: int
