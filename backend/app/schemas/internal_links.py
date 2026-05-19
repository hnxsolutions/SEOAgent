"""Schemas for deterministic internal link recommendations."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InternalLinkRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    crawl_job_id: UUID
    project_id: Optional[UUID] = None
    tenant_id: UUID
    source_page_id: UUID
    source_url: str
    target_page_id: UUID
    target_url: str
    suggested_anchor_text: str
    suggested_context_snippet: Optional[str] = None
    reason: str
    confidence_score: float
    priority_score: float
    status: str
    recommendation_type: str
    semantic_similarity: Optional[float] = None
    evidence: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


class InternalLinkRecommendationListResponse(BaseModel):
    recommendations: List[InternalLinkRecommendationResponse]
    limit: int
    offset: int
    has_more: bool = False


class InternalLinkGenerationResponse(BaseModel):
    crawl_id: UUID
    created_count: int
    recommendations: List[InternalLinkRecommendationResponse]


class InternalLinkSummaryResponse(BaseModel):
    crawl_id: UUID
    project_id: Optional[UUID] = None
    total_pages: int = 0
    orphan_pages: int = 0
    weakly_linked_pages: int = 0
    pages_with_too_few_internal_links: int = 0
    pages_with_excessive_internal_links: int = 0
    duplicate_anchor_text_risks: int = 0
    total_recommendations: int = 0
    average_priority_score: float = 0
    recommendations_by_status: Dict[str, int] = Field(default_factory=dict)
    recommendations_by_type: Dict[str, int] = Field(default_factory=dict)
