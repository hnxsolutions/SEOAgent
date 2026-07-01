"""Schemas for GSC indexing intelligence and validation APIs."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.indexing import (
    GSCFixValidationRunStatus,
    GSCIndexingIssueSeverity,
    GSCIndexingIssueStatus,
    GSCIndexingIssueType,
    GSCUrlInspectionRunStatus,
)
from app.schemas.planner import SeoTaskResponse
from app.schemas.repo_agent import SeoCodeIssueResponse, SeoCodePatchResponse


class IndexingInspectRequest(BaseModel):
    urls: Optional[List[str]] = Field(default=None, max_length=100)
    limit: Optional[int] = Field(default=None, ge=1, le=100)
    language_code: Optional[str] = Field(default=None, min_length=2, max_length=16)


class GSCUrlInspectionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    gsc_property_id: UUID
    status: GSCUrlInspectionRunStatus
    requested_url_count: int = 0
    inspected_url_count: int = 0
    failed_url_count: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime


class GSCUrlInspectionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    inspection_run_id: UUID
    page_url: str
    inspection_result_link: Optional[str] = None
    verdict: Optional[str] = None
    coverage_state: Optional[str] = None
    indexing_state: Optional[str] = None
    robots_txt_state: Optional[str] = None
    page_fetch_state: Optional[str] = None
    google_canonical: Optional[str] = None
    user_canonical: Optional[str] = None
    sitemap_urls: Optional[List[str]] = None
    referring_urls: Optional[List[str]] = None
    last_crawl_time: Optional[datetime] = None
    crawled_as: Optional[str] = None
    mobile_usability_verdict: Optional[str] = None
    rich_results_verdict: Optional[str] = None
    raw_result: Optional[Dict[str, Any]] = None
    created_at: datetime


class GSCIndexingIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    inspection_result_id: UUID
    page_url: str
    issue_type: GSCIndexingIssueType
    severity: GSCIndexingIssueSeverity
    likely_cause: str
    recommended_fix: str
    linked_repo_issue_id: Optional[UUID] = None
    linked_patch_id: Optional[UUID] = None
    status: GSCIndexingIssueStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class GSCUrlInspectionRunListResponse(BaseModel):
    runs: List[GSCUrlInspectionRunResponse]
    limit: int
    offset: int
    has_more: bool = False


class GSCUrlInspectionRunDetailResponse(BaseModel):
    run: GSCUrlInspectionRunResponse
    results: List[GSCUrlInspectionResultResponse]
    issues: List[GSCIndexingIssueResponse]


class GSCIndexingIssueListResponse(BaseModel):
    issues: List[GSCIndexingIssueResponse]
    limit: int
    offset: int
    has_more: bool = False


class IndexingFixPlanResponse(BaseModel):
    issue: GSCIndexingIssueResponse
    planner_task: Optional[SeoTaskResponse] = None
    repo_issue: Optional[SeoCodeIssueResponse] = None
    patch: Optional[SeoCodePatchResponse] = None
    safety: str


class IndexingValidationRequest(BaseModel):
    validation_after_days: int = Field(7, ge=1, le=60)
    run_now: bool = True


class GSCFixValidationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    issue_id: Optional[UUID] = None
    patch_id: Optional[UUID] = None
    pull_request_id: Optional[UUID] = None
    status: GSCFixValidationRunStatus
    validation_after_days: int = 7
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class GSCFixValidationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    validation_run_id: UUID
    issue_id: UUID
    page_url: str
    previous_issue_type: GSCIndexingIssueType
    current_verdict: Optional[str] = None
    current_coverage_state: Optional[str] = None
    fixed: bool
    still_failing: bool
    notes: Optional[str] = None
    raw_result: Optional[Dict[str, Any]] = None
    created_at: datetime


class IndexingValidationResponse(BaseModel):
    validation_run: GSCFixValidationRunResponse
    result: Optional[GSCFixValidationResultResponse] = None
    issue: Optional[GSCIndexingIssueResponse] = None


class IndexingSummaryResponse(BaseModel):
    project_id: UUID
    url_inspection_connected: bool = False
    indexed_urls: int
    not_indexed_urls: int
    issues_count: int
    issues_by_type: Dict[str, int]
    issues_by_status: Dict[str, int]
    latest_run: Optional[GSCUrlInspectionRunResponse] = None
    top_issues: List[GSCIndexingIssueResponse] = Field(default_factory=list)
    next_validation_date: datetime
