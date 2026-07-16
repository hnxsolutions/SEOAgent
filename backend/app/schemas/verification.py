"""Schemas for the after-merge verification + learning APIs."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.verification import VerificationStatus


class VerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    patch_id: UUID
    pull_request_id: Optional[UUID] = None
    issue_id: Optional[UUID] = None
    patch_type: str
    issue_type: Optional[str] = None
    status: VerificationStatus
    scheduled_at: datetime
    verified_at: Optional[datetime] = None
    baseline_seo_run_id: Optional[UUID] = None
    followup_seo_run_id: Optional[UUID] = None
    baseline_score: Optional[float] = None
    followup_score: Optional[float] = None
    issue_resolved: Optional[bool] = None
    improvement_pct: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    merged_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class VerificationListResponse(BaseModel):
    verifications: List[VerificationResponse]
    total: int


class SimulateMergeResponse(BaseModel):
    pull_request_id: str
    status: str
    verifications_enqueued: int
    scheduled_at: str


class LearningStatsResponse(BaseModel):
    total_verifications: int
    finalized: int
    by_status: Dict[str, int]
    success_rate: Optional[float] = None
    average_improvement_pct: Optional[float] = None
    most_successful_fixes: List[Dict[str, Any]]
    least_successful_fixes: List[Dict[str, Any]]
    confidence_by_patch_type: Dict[str, Any]
