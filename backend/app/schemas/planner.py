"""Schemas for weekly autonomous SEO planner APIs."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.planner import (
    SeoPlannerRunStatus,
    SeoPlannerRunType,
    SeoTaskEffort,
    SeoTaskImpact,
    SeoTaskPriority,
    SeoTaskSourceType,
    SeoTaskStatus,
    SeoTaskType,
)


class PlannerRunRequest(BaseModel):
    run_type: SeoPlannerRunType = SeoPlannerRunType.manual
    target_week_start: Optional[datetime] = None


class SeoPlannerRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    status: SeoPlannerRunStatus
    run_type: SeoPlannerRunType
    target_week_start: datetime
    target_week_end: datetime
    crawl_id: Optional[UUID] = None
    audit_id: Optional[UUID] = None
    semantic_run_id: Optional[UUID] = None
    internal_link_run_id: Optional[UUID] = None
    content_optimization_run_id: Optional[UUID] = None
    geo_aeo_run_id: Optional[UUID] = None
    gsc_sync_job_id: Optional[UUID] = None
    blog_plan_id: Optional[UUID] = None
    repo_scan_run_id: Optional[UUID] = None
    tasks_created: int = 0
    high_priority_tasks: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoPlannerRunListResponse(BaseModel):
    runs: List[SeoPlannerRunResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    planner_run_id: UUID
    task_type: SeoTaskType
    title: str
    description: str
    source_type: SeoTaskSourceType
    source_reference_id: Optional[UUID] = None
    target_page_url: Optional[str] = None
    target_keyword: Optional[str] = None
    priority: SeoTaskPriority
    priority_score: float
    estimated_impact: SeoTaskImpact
    effort: SeoTaskEffort
    status: SeoTaskStatus
    due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoTaskListResponse(BaseModel):
    tasks: List[SeoTaskResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoWeeklyReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    planner_run_id: UUID
    summary: str
    wins: Optional[list] = None
    risks: Optional[list] = None
    technical_seo_summary: Optional[dict] = None
    search_console_summary: Optional[dict] = None
    content_summary: Optional[dict] = None
    geo_aeo_summary: Optional[dict] = None
    blog_summary: Optional[dict] = None
    repo_patch_summary: Optional[dict] = None
    next_week_priorities: Optional[list] = None
    created_at: datetime


class PlannerProjectSummaryResponse(BaseModel):
    project_id: UUID
    open_tasks: int
    total_tasks: int
    tasks_by_status: dict
    tasks_by_priority: dict
    latest_run_id: Optional[UUID] = None
    latest_run_status: Optional[SeoPlannerRunStatus] = None
    top_tasks: List[SeoTaskResponse]


class PlannerDuplicateTaskRef(BaseModel):
    id: UUID
    title: str
    status: SeoTaskStatus
    priority: SeoTaskPriority
    priority_score: float
    updated_at: Optional[datetime] = None
    source_reference_id: Optional[UUID] = None


class PlannerDuplicateGroupResponse(BaseModel):
    group_key: str
    group_type: str
    task_type: SeoTaskType
    source_type: SeoTaskSourceType
    target_page_url: Optional[str] = None
    target_keyword: Optional[str] = None
    normalized_title: str
    keep_task: PlannerDuplicateTaskRef
    duplicate_tasks: List[PlannerDuplicateTaskRef]


class PlannerDedupeResponse(BaseModel):
    project_id: UUID
    dry_run: bool = True
    duplicate_groups: List[PlannerDuplicateGroupResponse]
    duplicate_group_count: int
    duplicate_task_count: int
    skipped_task_count: int = 0
