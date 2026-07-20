"""Technology Fingerprint routes.

The fingerprint is the first thing produced for a project — the complete tech
stack detected from the live site (no credentials). GET returns the saved
fingerprint (reused, never re-detected); POST /analyze forces a fresh detection
(the "Re-analyze Technology" action).
"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.fingerprint import FingerprintService

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


class FingerprintResponse(BaseModel):
    project_id: UUID
    status: str
    source: Optional[str] = None
    source_url: Optional[str] = None
    primary_framework: Optional[str] = None
    secondary_framework: Optional[str] = None
    primary_cms: Optional[str] = None
    primary_language: Optional[str] = None
    rendering: Optional[str] = None
    hosting: Optional[str] = None
    cdn: Optional[str] = None
    scores: Dict[str, Any] = {}
    strategy: Dict[str, Any] = {}
    technologies: List[Dict[str, Any]] = []
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    detected_at: Optional[str] = None
    error: Optional[str] = None


def _shape(fp, by_category: Dict[str, List[dict]]) -> FingerprintResponse:
    return FingerprintResponse(
        project_id=fp.project_id,
        status=getattr(fp.status, "value", fp.status),
        source=getattr(fp.source, "value", fp.source),
        source_url=fp.source_url,
        primary_framework=fp.primary_framework,
        secondary_framework=fp.secondary_framework,
        primary_cms=fp.primary_cms,
        primary_language=fp.primary_language,
        rendering=fp.rendering,
        hosting=fp.hosting,
        cdn=fp.cdn,
        scores=fp.scores or {},
        strategy=fp.strategy or {},
        technologies=fp.technologies or [],
        by_category=by_category,
        detected_at=fp.detected_at.isoformat() if fp.detected_at else None,
        error=fp.error,
    )


@router.get("/projects/{project_id}")
async def get_fingerprint(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    """Return the saved fingerprint (business-friendly summary). Degrades to a
    not-analyzed shape when the project has never been fingerprinted."""
    return await FingerprintService(db).summary(project_id, _tenant_id(current_user))


@router.post("/projects/{project_id}/analyze")
async def analyze_fingerprint(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    force: bool = True,
):
    """Detect the project's technology stack. force=True (default) re-analyzes;
    force=False reuses an existing completed fingerprint."""
    try:
        fp = await FingerprintService(db).analyze(project_id, _tenant_id(current_user), force=force)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    svc = FingerprintService(db)
    return _shape(fp, svc._group(fp.technologies or []))
