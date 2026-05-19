"""Schemas for local content optimization suggestions."""
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContentOptimizationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    crawl_id: UUID
    project_id: Optional[UUID] = None
    tenant_id: UUID
    status: str
    progress: int = 0
    model: str
    total_pages: int = 0
    total_suggestions: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ContentOptimizationSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    run_id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    crawl_id: UUID
    page_id: UUID
    suggestion_type: str
    current_value: Optional[str] = None
    suggested_value: str
    reason: str
    priority_score: float
    confidence_score: float
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


class ContentOptimizationSuggestionListResponse(BaseModel):
    suggestions: List[ContentOptimizationSuggestionResponse]
    limit: int
    offset: int
    has_more: bool = False


class ContentOptimizationSummaryResponse(BaseModel):
    crawl_id: UUID
    project_id: Optional[UUID] = None
    total_suggestions: int = 0
    pages_with_suggestions: int = 0
    average_priority_score: float = 0
    average_confidence_score: float = 0
    suggestions_by_status: Dict[str, int] = Field(default_factory=dict)
    suggestions_by_type: Dict[str, int] = Field(default_factory=dict)
