"""AI SEO Growth Engine routes.

Growth score, keyword opportunities (by intent), content gaps, topic clusters,
framework-aware blog roadmap + content calendar, EEAT assessment, and a labelled
traffic forecast. Recommendations only — never edits a site.
"""
from typing import Annotated, Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.seo_growth import SeoGrowthEngine

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


@router.get("/projects/{project_id}/summary")
async def growth_summary(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                         db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoGrowthEngine(db).summary(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}/keywords")
async def growth_keywords(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]):
    return {"keywords": await SeoGrowthEngine(db).keyword_opportunities(project_id, _tenant_id(current_user))}


@router.get("/projects/{project_id}/content-gaps")
async def growth_gaps(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                      db: Annotated[AsyncSession, Depends(get_db)]):
    return {"content_gaps": await SeoGrowthEngine(db).content_gaps(project_id, _tenant_id(current_user))}


@router.get("/projects/{project_id}/clusters")
async def growth_clusters(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]):
    return {"clusters": await SeoGrowthEngine(db).topic_clusters(project_id, _tenant_id(current_user))}


@router.get("/projects/{project_id}/roadmap")
async def growth_roadmap(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                         db: Annotated[AsyncSession, Depends(get_db)]):
    return {"roadmap": await SeoGrowthEngine(db).blog_roadmap(project_id, _tenant_id(current_user))}


@router.get("/projects/{project_id}/calendar")
async def growth_calendar(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)],
                          days: int = Query(90, ge=30, le=90)) -> Dict[str, Any]:
    return await SeoGrowthEngine(db).content_calendar(project_id, _tenant_id(current_user), days=days)


@router.get("/projects/{project_id}/forecast")
async def growth_forecast(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoGrowthEngine(db).traffic_forecast(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}/eeat")
async def growth_eeat(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                      db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoGrowthEngine(db).eeat(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}/score")
async def growth_score(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                       db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoGrowthEngine(db).growth_score(project_id, _tenant_id(current_user))


@router.post("/projects/{project_id}/analyze")
async def growth_analyze(project_id: UUID, current_user: Annotated[dict, Depends(get_current_user)],
                         db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    try:
        snap = await SeoGrowthEngine(db).analyze(project_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"snapshot_id": str(snap.id), "growth_score": snap.growth_score,
            "keyword_opportunities": len(snap.keyword_opportunities or []),
            "content_gaps": len(snap.content_gaps or []),
            "blog_roadmap": len(snap.blog_roadmap or [])}


@router.get("/overview")
async def growth_overview(current_user: Annotated[dict, Depends(get_current_user)],
                          db: Annotated[AsyncSession, Depends(get_db)]) -> Dict[str, Any]:
    return await SeoGrowthEngine(db).mission_control_summary(_tenant_id(current_user))
