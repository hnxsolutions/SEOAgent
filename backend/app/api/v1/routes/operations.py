"""SEO Operations Engine routes (autonomous orchestrator).

Health score, next best actions, lifecycle, daily monitoring + change detection,
timeline, project insights, and the CEO-level tenant overview. Read/orchestrate
only — never modifies a site.
"""
from typing import Annotated, Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.seo_operations import SeoOperationsEngine

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


@router.get("/projects/{project_id}/health")
async def project_health(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                         db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoOperationsEngine(db).health(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}/next-actions")
async def project_next_actions(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                               db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    actions = await SeoOperationsEngine(db).next_best_actions(project_id, _tenant_id(current_user))
    return {"actions": actions}


@router.get("/projects/{project_id}/lifecycle")
async def project_lifecycle(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                            db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoOperationsEngine(db).lifecycle(project_id, _tenant_id(current_user))


@router.post("/projects/{project_id}/monitor")
async def project_monitor(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    try:
        return await SeoOperationsEngine(db).monitor(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/changes")
async def project_changes(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]):
    return {"changes": await SeoOperationsEngine(db).changes(project_id, _tenant_id(current_user))}


@router.get("/projects/{project_id}/timeline")
async def project_timeline(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                           db: Annotated[AsyncSession, Depends(get_db)]):
    return {"timeline": await SeoOperationsEngine(db).timeline(project_id, _tenant_id(current_user))}


@router.get("/projects/{project_id}/insights")
async def project_insights(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                           db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoOperationsEngine(db).insights(project_id, _tenant_id(current_user))


@router.post("/monitor-all")
async def monitor_all(current_user: Annotated[dict, Depends(get_current_user)],
                      db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoOperationsEngine(db).monitor_all(_tenant_id(current_user))


@router.get("/overview")
async def ceo_overview(current_user: Annotated[dict, Depends(get_current_user)],
                       db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoOperationsEngine(db).ceo_overview(_tenant_id(current_user))
