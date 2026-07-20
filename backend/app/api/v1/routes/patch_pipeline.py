"""Autonomous patch pipeline routes.

Run the full lifecycle for a project's ready SEO patches (apply -> branch ->
commit -> PR -> deploy -> verify -> learn) and inspect the live stage status.
Degrades gracefully (status=blocked) when no repository is connected.
"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.patch_pipeline import PatchPipelineService

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    project_id: UUID
    framework: Optional[str] = None
    status: str
    current_stage: Optional[str] = None
    stages: List[Dict[str, Any]] = []
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    diff_summary: Optional[str] = None
    pr_url: Optional[str] = None
    pr_status: Optional[str] = None
    validation_status: Optional[str] = None
    patches_total: Optional[int] = None
    patches_applied: Optional[int] = None
    patches_failed: Optional[int] = None
    ready_for_pr: Optional[bool] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@router.post("/projects/{project_id}/run", response_model=PipelineResponse)
async def run_pipeline(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        return await PatchPipelineService(db).run(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/summary")
async def pipeline_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    return await PatchPipelineService(db).summary(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}")
async def list_pipelines(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    items = await PatchPipelineService(db).list_pipelines(project_id, _tenant_id(current_user))
    return {"items": [PipelineResponse.model_validate(i) for i in items], "total": len(items)}


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pipeline = await PatchPipelineService(db).get(pipeline_id, _tenant_id(current_user))
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline
