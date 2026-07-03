"""Schemas for production SEO schedules."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.scheduler import SeoScheduledRunStatus, SeoScheduleFrequency, SeoScheduleType
from app.schemas.search_console import GSCSyncJobResponse


class SeoScheduleCreate(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    schedule_type: SeoScheduleType
    frequency: SeoScheduleFrequency
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=31)
    hour: int = Field(9, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    timezone: str = Field("UTC", min_length=1, max_length=64)
    is_enabled: bool = True


class SeoScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    schedule_type: Optional[SeoScheduleType] = None
    frequency: Optional[SeoScheduleFrequency] = None
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=31)
    hour: Optional[int] = Field(None, ge=0, le=23)
    minute: Optional[int] = Field(None, ge=0, le=59)
    timezone: Optional[str] = Field(None, min_length=1, max_length=64)
    is_enabled: Optional[bool] = None


class SeoScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    name: str
    schedule_type: SeoScheduleType
    frequency: SeoScheduleFrequency
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    hour: int
    minute: int
    timezone: str
    is_enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoScheduleListResponse(BaseModel):
    schedules: List[SeoScheduleResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoScheduledRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    schedule_id: UUID
    status: SeoScheduledRunStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    planner_run_id: Optional[UUID] = None
    gsc_sync_job_id: Optional[UUID] = None
    crawl_id: Optional[UUID] = None
    audit_id: Optional[UUID] = None
    semantic_run_id: Optional[UUID] = None
    repo_scan_run_id: Optional[UUID] = None
    blog_plan_id: Optional[UUID] = None
    summary: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoScheduledRunListResponse(BaseModel):
    runs: List[SeoScheduledRunResponse]
    limit: int
    offset: int
    has_more: bool = False


class SchedulerTickResponse(BaseModel):
    due_count: int
    runs_created: int
    runs: List[SeoScheduledRunResponse]
    gsc_monitor_due_count: int = 0
    gsc_monitor_jobs_created: int = 0
    gsc_monitor_jobs: List[GSCSyncJobResponse] = Field(default_factory=list)
