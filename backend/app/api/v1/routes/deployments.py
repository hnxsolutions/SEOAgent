"""Deployment intelligence routes."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.deployment import (
    DeploymentListResponse,
    DeploymentResponse,
    DeploymentStatusUpdate,
)
from app.services.deployment import DeploymentEngine

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.get("/provider-health")
async def deployment_provider_health(
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Configured/unconfigured state of each deployment provider adapter."""
    from app.deployment.adapters import provider_health

    return {"providers": provider_health()}


@router.get("/projects/{project_id}/stats")
async def deployment_stats(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Deployment success/failure/duration + per-provider reliability (learning evidence)."""
    return await DeploymentEngine(db).deployment_stats(_tenant_id(current_user))


@router.post("/{deployment_id}/poll", response_model=DeploymentResponse)
async def poll_deployment(
    deployment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Poll the provider adapter for a deployment's live status (credential-gated)."""
    engine = DeploymentEngine(db)
    try:
        return await engine.poll_deployment(deployment_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}", response_model=DeploymentListResponse)
async def list_deployments(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    engine = DeploymentEngine(db)
    items = await engine.list_deployments(project_id, _tenant_id(current_user))
    return DeploymentListResponse(deployments=items, total=len(items))


@router.get("/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    engine = DeploymentEngine(db)
    deployment = await engine.get_deployment(deployment_id, _tenant_id(current_user))
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    return deployment


@router.post("/{deployment_id}/status", response_model=DeploymentResponse)
async def update_deployment_status(
    deployment_id: UUID,
    payload: DeploymentStatusUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Report deployment status (generic webhook / simulate deploy). On success
    the linked after-merge verifications are accelerated so SEO is re-measured
    against the live site."""
    engine = DeploymentEngine(db)
    try:
        return await engine.update_status(
            deployment_id,
            _tenant_id(current_user),
            payload.status.value,
            deployment_url=payload.deployment_url,
            logs=payload.logs,
            commit_sha=payload.commit_sha,
            external_id=payload.external_id,
            error_message=payload.error_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
