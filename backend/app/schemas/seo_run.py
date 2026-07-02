"""Schemas for one-click SEO run orchestration."""
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.seo_run import SeoRunStage, SeoRunStageStatus, SeoRunStatus


class SeoRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    status: SeoRunStatus
    current_stage: SeoRunStage
    stage_statuses: Dict[str, SeoRunStageStatus]
    stage_errors: Dict[str, str]
    crawl_id: Optional[UUID] = None
    audit_id: Optional[UUID] = None
    semantic_index_run_id: Optional[UUID] = None
    content_optimization_run_id: Optional[UUID] = None
    planner_run_id: Optional[UUID] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoRunListResponse(BaseModel):
    runs: List[SeoRunResponse]
    limit: int
    offset: int
    has_more: bool = False
