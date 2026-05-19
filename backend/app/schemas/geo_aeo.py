"""Schemas for GEO/AEO scoring and recommendations."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GeoAeoRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    crawl_id: UUID
    project_id: Optional[UUID] = None
    tenant_id: UUID
    status: str
    progress: int = 0
    model: Optional[str] = None
    total_pages: int = 0
    total_recommendations: int = 0
    average_geo_score: float = 0
    average_aeo_score: float = 0
    average_citation_readiness_score: float = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class GeoAeoPageScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    run_id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    crawl_id: UUID
    page_id: UUID
    url: str
    geo_score: float
    aeo_score: float
    citation_readiness_score: float
    answer_block_score: float
    entity_clarity_score: float
    schema_readiness_score: float
    trust_signal_score: float
    topical_completeness_score: float
    score_breakdown: Optional[Dict[str, Any]] = None
    extracted_entities: Optional[List[str]] = None
    extracted_claims: Optional[List[str]] = None
    evidence: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class GeoAeoRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    run_id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    crawl_id: UUID
    page_id: UUID
    recommendation_type: str
    recommendation_text: str
    reason: str
    priority_score: float
    confidence_score: float
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


class GeoAeoRecommendationListResponse(BaseModel):
    recommendations: List[GeoAeoRecommendationResponse]
    limit: int
    offset: int
    has_more: bool = False


class GeoAeoSummaryResponse(BaseModel):
    crawl_id: UUID
    project_id: Optional[UUID] = None
    run_id: Optional[UUID] = None
    status: Optional[str] = None
    total_pages: int = 0
    total_recommendations: int = 0
    average_geo_score: float = 0
    average_aeo_score: float = 0
    average_citation_readiness_score: float = 0
    average_answer_block_score: float = 0
    average_entity_clarity_score: float = 0
    average_schema_readiness_score: float = 0
    average_trust_signal_score: float = 0
    average_topical_completeness_score: float = 0
    recommendations_by_status: Dict[str, int] = Field(default_factory=dict)
    recommendations_by_type: Dict[str, int] = Field(default_factory=dict)
