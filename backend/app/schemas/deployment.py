"""Schemas for deployment intelligence APIs."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.deployment import DeploymentProvider, DeploymentStatus


class DeploymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    pull_request_id: Optional[UUID] = None
    provider: DeploymentProvider
    status: DeploymentStatus
    commit_sha: Optional[str] = None
    deployment_url: Optional[str] = None
    external_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    logs: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None


class DeploymentListResponse(BaseModel):
    deployments: List[DeploymentResponse]
    total: int


class DeploymentStatusUpdate(BaseModel):
    """Payload for the generic deployment webhook / simulate-deploy action."""
    status: DeploymentStatus
    deployment_url: Optional[str] = None
    commit_sha: Optional[str] = None
    external_id: Optional[str] = None
    logs: Optional[str] = None
    error_message: Optional[str] = None
