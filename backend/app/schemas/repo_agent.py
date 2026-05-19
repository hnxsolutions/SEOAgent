"""Schemas for the review-only SEO code repository agent."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.repo_agent import (
    PatchApplyResultStatus,
    PatchApplyRunStatus,
    PatchValidationStatus,
    PullRequestProvider,
    PullRequestStatus,
    RepoConnectionStatus,
    RepoProvider,
    RepoScanRunStatus,
    SeoCodeIssueSeverity,
    SeoCodeIssueSource,
    SeoCodeIssueStatus,
    SeoCodeIssueType,
    SeoCodePatchRisk,
    SeoCodePatchStatus,
    SeoCodePatchType,
)


class RepoConnectionCreate(BaseModel):
    project_id: Optional[UUID] = None
    provider: RepoProvider = RepoProvider.local
    repo_url: Optional[str] = None
    local_path: Optional[str] = None
    default_branch: Optional[str] = None
    framework: Optional[str] = None


class RepoConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    provider: RepoProvider
    repo_url: Optional[str] = None
    local_path: Optional[str] = None
    default_branch: Optional[str] = None
    framework: Optional[str] = None
    status: RepoConnectionStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class RepoConnectionListResponse(BaseModel):
    connections: List[RepoConnectionResponse]
    limit: int
    offset: int
    has_more: bool = False


class RepoScanRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: UUID
    status: RepoScanRunStatus
    framework_detected: Optional[str] = None
    files_scanned: int = 0
    issues_found: int = 0
    patches_created: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class RepoFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: UUID
    scan_run_id: UUID
    file_path: str
    file_type: str
    content_hash: str
    detected_purpose: str
    has_metadata: bool
    has_jsonld: bool
    has_canonical: bool
    has_open_graph: bool
    has_twitter_meta: bool
    has_sitemap: bool
    has_robots: bool
    created_at: datetime


class RepoFileListResponse(BaseModel):
    files: List[RepoFileResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoCodeIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: UUID
    scan_run_id: UUID
    file_id: Optional[UUID] = None
    issue_type: SeoCodeIssueType
    severity: SeoCodeIssueSeverity
    title: str
    description: str
    recommended_fix: str
    source_reference_type: SeoCodeIssueSource
    source_reference_id: Optional[UUID] = None
    status: SeoCodeIssueStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoCodeIssueListResponse(BaseModel):
    issues: List[SeoCodeIssueResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoCodePatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: UUID
    scan_run_id: UUID
    issue_id: UUID
    file_path: str
    patch_type: SeoCodePatchType
    original_content_hash: str
    diff_text: str
    proposed_content: str
    explanation: str
    risk_level: SeoCodePatchRisk
    status: SeoCodePatchStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoCodePatchListResponse(BaseModel):
    patches: List[SeoCodePatchResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoCodePatchGenerateResponse(BaseModel):
    scan_id: UUID
    patches_created: int = Field(ge=0)
    patches: List[SeoCodePatchResponse]


class PatchApplyRequest(BaseModel):
    allow_high_risk: bool = False
    run_validation: bool = False
    validation_commands: Optional[List[str]] = None


class PatchApplyRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: UUID
    scan_run_id: UUID
    branch_name: Optional[str] = None
    status: PatchApplyRunStatus
    patches_requested: int = 0
    patches_applied: int = 0
    patches_failed: int = 0
    validation_status: PatchValidationStatus
    validation_output: Optional[str] = None
    git_diff_summary: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class PatchApplyResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    apply_run_id: UUID
    patch_id: UUID
    file_path: str
    status: PatchApplyResultStatus
    reason: Optional[str] = None
    original_content_hash: Optional[str] = None
    new_content_hash: Optional[str] = None
    backup_path: Optional[str] = None
    created_at: datetime


class PatchApplyResultListResponse(BaseModel):
    results: List[PatchApplyResultResponse]
    limit: int
    offset: int
    has_more: bool = False


class PullRequestCreateRequest(BaseModel):
    force_pr_on_validation_failure: bool = False
    draft: bool = True
    title: Optional[str] = None
    description: Optional[str] = None


class PullRequestRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: UUID
    apply_run_id: UUID
    provider: PullRequestProvider
    branch_name: str
    base_branch: str
    commit_sha: Optional[str] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    status: PullRequestStatus
    title: str
    description: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
