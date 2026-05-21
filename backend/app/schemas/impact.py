"""Schemas for SEO impact experiments."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.impact import (
    SeoImpactDataSource,
    SeoImpactExperimentStatus,
    SeoImpactExperimentType,
    SeoImpactOutcome,
    SeoImpactSnapshotType,
    SeoImpactSourceType,
)


class SeoImpactExperimentCreate(BaseModel):
    project_id: UUID
    experiment_type: SeoImpactExperimentType
    source_type: SeoImpactSourceType = SeoImpactSourceType.manual
    source_reference_id: Optional[UUID] = None
    target_page_url: str = Field(..., min_length=1, max_length=2048)
    target_query: Optional[str] = Field(None, max_length=1000)
    target_keywords: Optional[List[str]] = None
    baseline_start_date: datetime
    baseline_end_date: datetime
    action_date: Optional[datetime] = None
    review_start_date: Optional[datetime] = None
    review_end_date: Optional[datetime] = None
    review_after_days: int = Field(14, ge=1, le=365)
    notes: Optional[str] = None


class SeoImpactExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    experiment_type: SeoImpactExperimentType
    source_type: SeoImpactSourceType
    source_reference_id: Optional[UUID] = None
    target_page_url: str
    target_query: Optional[str] = None
    target_keywords: Optional[List[str]] = None
    baseline_start_date: datetime
    baseline_end_date: datetime
    action_date: Optional[datetime] = None
    review_start_date: Optional[datetime] = None
    review_end_date: Optional[datetime] = None
    review_after_days: int
    status: SeoImpactExperimentStatus
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoImpactExperimentListResponse(BaseModel):
    experiments: List[SeoImpactExperimentResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoImpactSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    experiment_id: UUID
    snapshot_type: SeoImpactSnapshotType
    date_start: datetime
    date_end: datetime
    query: Optional[str] = None
    page_url: str
    clicks: int
    impressions: int
    ctr: float
    position: float
    data_source: SeoImpactDataSource
    created_at: datetime


class SeoImpactResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    experiment_id: UUID
    clicks_delta: int
    impressions_delta: int
    ctr_delta: float
    position_delta: float
    percentage_clicks_change: Optional[float] = None
    percentage_impressions_change: Optional[float] = None
    outcome: SeoImpactOutcome
    confidence_score: float
    summary: str
    created_at: datetime


class SeoImpactSummaryResponse(BaseModel):
    project_id: UUID
    total_experiments: int
    by_status: dict[str, int]
    by_outcome: dict[str, int]
    ready_for_review: int
    message: Optional[str] = None

