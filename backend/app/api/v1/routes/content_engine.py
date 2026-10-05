"""Content engine and schedule provisioning endpoints.

Everything here is a manual trigger for something the scheduler already does on
its own. They exist so an operator can run a scan now rather than wait for
Monday, and so a project created before autonomous provisioning can be repaired
without touching the database.
"""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.database import get_db
from app.services.content_engine import ContentEngineService
from app.services.schedule_provisioning import (
    MAX_BLOGS_PER_WEEK,
    ScheduleProvisioningService,
)

router = APIRouter()


def _tenant_id(current_user: dict) -> UUID:
    return current_user["tenant_id"]


@router.post("/projects/{project_id}/provision-schedules")
async def provision_schedules(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    blogs_per_week: int = Query(2, ge=0, le=MAX_BLOGS_PER_WEEK),
):
    """Create any missing recurring schedules. Safe to call repeatedly."""
    return await ScheduleProvisioningService(db).provision(
        project_id, _tenant_id(current_user), blogs_per_week=blogs_per_week
    )


@router.put("/projects/{project_id}/blogs-per-week")
async def set_blogs_per_week(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    count: int = Query(..., ge=0, le=MAX_BLOGS_PER_WEEK),
):
    """Change the drafting cadence. Extra slots are disabled, never deleted."""
    return await ScheduleProvisioningService(db).set_blogs_per_week(
        project_id, _tenant_id(current_user), count
    )


@router.post("/projects/{project_id}/scan-opportunities")
async def scan_opportunities(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(15, ge=1, le=50),
):
    """Rank free first-party signals into reviewable topics."""
    return await ContentEngineService(db).scan_opportunities(
        project_id, _tenant_id(current_user), limit=limit
    )


@router.post("/projects/{project_id}/draft-next")
async def draft_next(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Draft the best waiting topic, or report why the slot was skipped."""
    return await ContentEngineService(db).draft_next(project_id, _tenant_id(current_user))


@router.get("/drafts/{draft_id}/validation")
async def validate_draft(
    draft_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SEO and AEO scores for a draft, with the specific failures listed."""
    result = await ContentEngineService(db).validate_draft(draft_id, _tenant_id(current_user))
    if result.get("seo_score") is None and "Draft not found." in (result.get("issues") or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return result


@router.get("/projects/{project_id}/content-performance")
async def content_performance(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Measured performance of published articles, plus refresh proposals."""
    return await ContentEngineService(db).review_performance(project_id, _tenant_id(current_user))


# ---------------------------------------------------------------------------
# Website knowledge profile
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/profile")
async def get_website_profile(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """What the agent understands about the site, with per-field provenance."""
    from app.services.website_profile import WebsiteProfileService

    service = WebsiteProfileService(db)
    profile = await service.get(project_id, _tenant_id(current_user))
    if not profile:
        return {
            "available": False,
            "reason": "No profile yet — it is built from the site's first completed crawl.",
        }
    return {"available": True, **service.to_dict(profile)}


@router.post("/projects/{project_id}/profile/build")
async def build_website_profile(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    force: bool = Query(False, description="Rebuild even if the site has not changed"),
    use_llm: bool = Query(True, description="Allow one local-model call for semantic fields"),
):
    """Build or refresh the profile. Reuses the existing one when unchanged."""
    from app.services.website_profile import WebsiteProfileService

    return await WebsiteProfileService(db).build(
        project_id, _tenant_id(current_user), force=force, use_llm=use_llm
    )


# ---------------------------------------------------------------------------
# Clusters and cannibalisation
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/clusters")
async def list_clusters(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The topic graph: pillars, supporting articles, service pages and gaps."""
    from app.services.content_clusters import ContentClusterService

    clusters = await ContentClusterService(db).list_clusters(project_id, _tenant_id(current_user))
    return {"clusters": clusters, "count": len(clusters)}


@router.post("/projects/{project_id}/clusters/rebuild")
async def rebuild_clusters(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Recompute clusters from current opportunities and attach real nodes."""
    from app.services.content_clusters import ContentClusterService

    return await ContentClusterService(db).rebuild(project_id, _tenant_id(current_user))


@router.get("/projects/{project_id}/cannibalisation")
async def check_cannibalisation(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    topic: str = Query(..., min_length=3, max_length=300),
):
    """Would writing this compete with something the site already has?"""
    from app.services.content_clusters import ContentClusterService

    return await ContentClusterService(db).check_cannibalisation(
        project_id, _tenant_id(current_user), topic
    )


# ---------------------------------------------------------------------------
# Refresh proposals
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/refresh-proposals")
async def list_refresh_proposals(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """Declines detected in published articles, waiting for a decision."""
    from app.models.content_refresh import RefreshStatus
    from app.services.content_refresh import ContentRefreshService

    parsed = None
    if status_filter:
        try:
            parsed = RefreshStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status_filter}")

    items = await ContentRefreshService(db).list_proposals(
        project_id, _tenant_id(current_user), status=parsed
    )
    return {"proposals": items, "count": len(items)}


@router.post("/refresh-proposals/{proposal_id}/{action}")
async def act_on_refresh_proposal(
    proposal_id: UUID,
    action: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    reason: Optional[str] = Query(None, max_length=2000),
):
    """Approve, reject, apply or verify. Illegal moves are refused by name."""
    from app.models.content_refresh import RefreshStatus
    from app.services.content_refresh import ContentRefreshService, RefreshTransitionError

    allowed = {
        "approve": RefreshStatus.approved,
        "reject": RefreshStatus.rejected,
        "apply": RefreshStatus.applied,
        "verify": RefreshStatus.verified,
    }
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    actor = str(current_user.get("email") or current_user.get("user_id") or "operator")
    try:
        return await ContentRefreshService(db).transition(
            proposal_id, _tenant_id(current_user), allowed[action], actor=actor, reason=reason
        )
    except RefreshTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
