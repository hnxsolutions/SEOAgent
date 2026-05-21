"""Schemas for SEO copy quality and compliance review."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.copy_review import (
    SeoCopyApprovalReadiness,
    SeoCopyComplianceProfile,
    SeoCopyRevisionStatus,
    SeoCopySourceType,
)


class SeoCopyReviewRequest(BaseModel):
    project_id: UUID
    source_type: SeoCopySourceType = SeoCopySourceType.metadata
    source_reference_id: Optional[UUID] = None
    page_url: Optional[str] = Field(None, max_length=2048)
    target_keyword: Optional[str] = Field(None, max_length=1000)
    original_title: Optional[str] = None
    original_description: Optional[str] = None
    compliance_profile: Optional[SeoCopyComplianceProfile] = None
    apply_revision: bool = False


class SeoCopyPolicyRequest(BaseModel):
    project_id: UUID
    compliance_profile: SeoCopyComplianceProfile = SeoCopyComplianceProfile.default
    blocked_phrases: Optional[List[str]] = None
    allowed_topics: Optional[List[str]] = None
    notes: Optional[str] = None


class SeoCopyReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    source_type: SeoCopySourceType
    source_reference_id: Optional[UUID] = None
    page_url: Optional[str] = None
    target_keyword: Optional[str] = None
    original_title: Optional[str] = None
    original_description: Optional[str] = None
    reviewed_title: Optional[str] = None
    reviewed_description: Optional[str] = None
    quality_score: float
    compliance_score: float
    approval_readiness: SeoCopyApprovalReadiness
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    revision_notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoCopyReviewListResponse(BaseModel):
    reviews: List[SeoCopyReviewResponse]
    limit: int
    offset: int
    has_more: bool = False


class SeoCopyPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    compliance_profile: SeoCopyComplianceProfile
    blocked_phrases: Optional[List[str]] = None
    allowed_topics: Optional[List[str]] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoCopyRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    review_id: UUID
    source_type: SeoCopySourceType
    source_reference_id: Optional[UUID] = None
    revised_title: Optional[str] = None
    revised_description: Optional[str] = None
    reason: Optional[str] = None
    compliance_notes: Optional[List[str]] = None
    status: SeoCopyRevisionStatus
    created_at: datetime
    updated_at: Optional[datetime] = None


class SeoCopyReviewResult(BaseModel):
    review: SeoCopyReviewResponse
    revision: Optional[SeoCopyRevisionResponse] = None
    source_updated: bool = False


class RepoPatchCopyReviewResponse(BaseModel):
    scan_id: UUID
    patches_reviewed: int
    patches_updated: int
    ready: int
    needs_revision: int
    manual_review: int
    rejected: int
    reviews: List[SeoCopyReviewResponse]
