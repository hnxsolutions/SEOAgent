"""Schemas for robots.txt intelligence APIs."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.robots import (
    RobotsAnalysisStatus,
    RobotsIssueSeverity,
    RobotsIssueStatus,
    RobotsIssueType,
)


class RobotsIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    analysis_run_id: UUID
    issue_type: RobotsIssueType
    severity: RobotsIssueSeverity
    title: str
    description: str
    recommended_action: str
    evidence: Optional[Dict[str, Any]] = None
    status: RobotsIssueStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class RobotsAnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    robots_url: str
    status: RobotsAnalysisStatus
    http_status_code: Optional[int] = None
    content_hash: Optional[str] = None
    byte_size: int
    sitemap_directive_count: int
    user_agent_group_count: int
    issues_found: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class RobotsAnalysisListResponse(BaseModel):
    analyses: List[RobotsAnalysisRunResponse]
    limit: int
    offset: int
    has_more: bool


class RobotsIssueListResponse(BaseModel):
    issues: List[RobotsIssueResponse]
    limit: int
    offset: int
    has_more: bool


class RobotsIssueStatusUpdate(BaseModel):
    status: RobotsIssueStatus


class RobotsSummaryResponse(BaseModel):
    status: str
    latest_run_id: Optional[str] = None
    robots_url: Optional[str] = None
    issues_total: Optional[int] = None
    issues_by_severity: Dict[str, int] = {}
    sitemap_directive_count: Optional[int] = None
    delta: Dict[str, Any] = {}
