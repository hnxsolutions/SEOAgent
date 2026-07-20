"""Live site validation routes."""
from typing import Annotated, Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.site_validation import SiteValidationService

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


def _item(v) -> Dict[str, Any]:
    return {
        "id": str(v.id), "url": v.url, "reachable": v.reachable, "http_status": v.http_status,
        "is_https": v.is_https, "passed_count": v.passed_count, "total_count": v.total_count,
        "checks": v.checks or {}, "error_message": v.error_message,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.post("/projects/{project_id}/validate")
async def validate_site(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    url: Optional[str] = Query(None, description="Override URL (defaults to the project's live domain)."),
):
    """Validate the live site now (HTTP 200, HTTPS, robots, sitemap, on-page tags, headers)."""
    service = SiteValidationService(db)
    try:
        v = await service.validate(project_id, _tenant_id(current_user), url=url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return _item(v)


@router.get("/projects/{project_id}/latest")
async def latest_validation(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    v = await SiteValidationService(db).latest(project_id, _tenant_id(current_user))
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No validation yet")
    return _item(v)


@router.get("/projects/{project_id}/history")
async def validation_history(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
):
    items = await SiteValidationService(db).list_validations(project_id, _tenant_id(current_user), limit=limit)
    return {"validations": [_item(v) for v in items], "total": len(items)}
