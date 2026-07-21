"""Post-merge deployment & verification routes.

Run the after-merge loop (deploy detection -> live-site verification ->
PageSpeed / CWV -> Search Console -> before/after comparison -> learning) and
read the results + activity timeline. All measurements come from the real
deployed site; credential-gated steps degrade gracefully.
"""
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.verification_pipeline import VerificationPipelineService

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


@router.post("/projects/{project_id}/run")
async def run_verification(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    try:
        dv = await VerificationPipelineService(db).run(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return VerificationPipelineService.shape(dv)


@router.get("/projects/{project_id}/summary")
async def verification_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    return await VerificationPipelineService(db).summary(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}")
async def list_verifications(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    items = await VerificationPipelineService(db).list_runs(project_id, _tenant_id(current_user))
    return {"items": [VerificationPipelineService.shape(i) for i in items], "total": len(items)}


@router.get("/summary")
async def mission_control_summary(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    return await VerificationPipelineService(db).mission_control_summary(_tenant_id(current_user))


@router.get("/{dv_id}")
async def get_verification(
    dv_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    dv = await VerificationPipelineService(db).get(dv_id, _tenant_id(current_user))
    if not dv:
        raise HTTPException(status_code=404, detail="Verification not found")
    return VerificationPipelineService.shape(dv)
