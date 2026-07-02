"""Schemas for one-click SEO run orchestration."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class SeoReportSection(BaseModel):
    key: str
    title: str
    summary: str
    status: str = "available"
    metrics: Dict[str, Any] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)


class SeoReportActionItem(BaseModel):
    title: str
    description: str
    priority: str = "medium"
    source_section: str
    target_url: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[datetime] = None


class SeoRunReportResponse(BaseModel):
    run_id: UUID
    tenant_id: UUID
    project_id: UUID
    project_name: str
    website_url: str
    run_status: str
    completed_at: Optional[datetime] = None
    generated_at: datetime
    crawl_pages_processed: int = 0
    audit_score: Optional[int] = None
    total_issues: int = 0
    issue_counts_by_severity: Dict[str, int] = Field(default_factory=dict)
    issue_counts_by_category: Dict[str, int] = Field(default_factory=dict)
    semantic_vector_count: int = 0
    content_suggestions_count: int = 0
    planner_tasks_count: int = 0
    data_availability: Dict[str, str] = Field(default_factory=dict)
    executive_summary: str
    sections: List[SeoReportSection] = Field(default_factory=list)
    top_audit_issues: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    content_suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    weekly_planner_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    next_actions: List[SeoReportActionItem] = Field(default_factory=list)
