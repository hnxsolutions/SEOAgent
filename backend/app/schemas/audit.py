"""Pydantic schemas for deterministic SEO audits."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SEOAuditRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    crawl_job_id: UUID
    project_id: Optional[UUID] = None
    tenant_id: UUID
    status: str
    progress: int = 0
    site_score: Optional[int] = None
    total_pages: int = 0
    total_issues: int = 0
    issue_counts_by_severity: Optional[Dict[str, int]] = None
    issue_counts_by_category: Optional[Dict[str, int]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SEOIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audit_run_id: UUID
    crawl_job_id: UUID
    crawl_page_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    tenant_id: UUID
    issue_type: str
    title: str
    message: str
    recommendation: Optional[str] = None
    severity: str
    category: str
    status: str
    url: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    score_impact: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class SEOIssueListResponse(BaseModel):
    issues: List[SEOIssueResponse]
    limit: int
    offset: int
    has_more: bool = False


class SEOPageScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audit_run_id: UUID
    crawl_job_id: UUID
    crawl_page_id: UUID
    project_id: Optional[UUID] = None
    tenant_id: UUID
    url: str
    score: int
    issue_count: int = 0
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0
    score_breakdown: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SEOSiteSummaryResponse(BaseModel):
    audit_run_id: UUID
    crawl_job_id: UUID
    project_id: Optional[UUID] = None
    status: str
    site_score: Optional[int] = None
    total_pages: int
    total_issues: int
    issue_counts_by_severity: Dict[str, int] = Field(default_factory=dict)
    issue_counts_by_category: Dict[str, int] = Field(default_factory=dict)
    top_issue_types: Dict[str, int] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
