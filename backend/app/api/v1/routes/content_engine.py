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


async def _require_project(db: AsyncSession, project_id: UUID, tenant_id: UUID) -> None:
    """404 for a project this tenant does not own.

    Every query in this module already filters on tenant_id, so nothing leaks
    without this — a foreign project simply returned zeros. But answering 200
    for a project that is not yours is still wrong: it makes a missing project
    and an empty one indistinguishable, and it invites a later endpoint to be
    written without the filter and have nobody notice.
    """
    from sqlalchemy import select

    from app.models.project import Project

    result = await db.execute(
        select(Project.id).where(Project.id == project_id, Project.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.post("/projects/{project_id}/provision-schedules")
async def provision_schedules(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    blogs_per_week: int = Query(2, ge=0, le=MAX_BLOGS_PER_WEEK),
):
    """Create any missing recurring schedules. Safe to call repeatedly."""
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
    return await ContentEngineService(db).draft_next(project_id, _tenant_id(current_user))


@router.get("/drafts/{draft_id}/validation")
async def validate_draft(
    draft_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SEO and AEO scores for a draft, with the specific failures listed."""
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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
    await _require_project(db, project_id, _tenant_id(current_user))
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


# ---------------------------------------------------------------------------
# Dashboard aggregates
#
# One request per screen. Rendering the Content Overview from the individual
# endpoints would take six round trips, and a page that fires six requests on
# every project switch is a page nobody leaves open.
# ---------------------------------------------------------------------------

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@router.get("/projects/{project_id}/overview")
async def content_overview(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Everything the Content Overview screen shows, in one set of queries."""
    await _require_project(db, project_id, _tenant_id(current_user))
    from sqlalchemy import func, select

    from app.models.blog import BlogDraft, BlogDraftStatus, BlogTopic, BlogTopicStatus
    from app.models.content_cluster import ClusterNodeType, ContentCluster, ContentClusterNode
    from app.models.content_refresh import ContentRefreshProposal, RefreshStatus
    from app.models.scheduler import SeoSchedule, SeoScheduleType
    from app.services.website_profile import WebsiteProfileService

    tenant_id = _tenant_id(current_user)

    async def count(model, *where):
        result = await db.execute(select(func.count()).select_from(model).where(*where))
        return int(result.scalar() or 0)

    topics_waiting = await count(
        BlogTopic,
        BlogTopic.project_id == project_id,
        BlogTopic.tenant_id == tenant_id,
        BlogTopic.status.in_([BlogTopicStatus.suggested, BlogTopicStatus.approved]),
    )
    drafts = await count(
        BlogDraft, BlogDraft.project_id == project_id, BlogDraft.tenant_id == tenant_id,
        BlogDraft.status == BlogDraftStatus.draft,
    )
    pending = await count(
        BlogDraft, BlogDraft.project_id == project_id, BlogDraft.tenant_id == tenant_id,
        BlogDraft.status == BlogDraftStatus.pending_approval,
    )
    published = await count(
        BlogDraft, BlogDraft.project_id == project_id, BlogDraft.tenant_id == tenant_id,
        BlogDraft.status == BlogDraftStatus.published,
    )
    refresh_pending = await count(
        ContentRefreshProposal,
        ContentRefreshProposal.project_id == project_id,
        ContentRefreshProposal.tenant_id == tenant_id,
        ContentRefreshProposal.status.in_([RefreshStatus.detected, RefreshStatus.pending_approval]),
    )
    clusters = await count(
        ContentCluster, ContentCluster.project_id == project_id, ContentCluster.tenant_id == tenant_id
    )

    gaps_result = await db.execute(
        select(func.count())
        .select_from(ContentClusterNode)
        .join(ContentCluster, ContentCluster.id == ContentClusterNode.cluster_id)
        .where(
            ContentCluster.project_id == project_id,
            ContentClusterNode.node_type == ClusterNodeType.missing,
        )
    )
    cluster_gaps = int(gaps_result.scalar() or 0)

    slots_result = await db.execute(
        select(SeoSchedule)
        .where(
            SeoSchedule.project_id == project_id,
            SeoSchedule.tenant_id == tenant_id,
            SeoSchedule.schedule_type == SeoScheduleType.blog_generation,
            SeoSchedule.is_enabled.is_(True),
        )
        .order_by(SeoSchedule.next_run_at)
    )
    slots = list(slots_result.scalars().all())

    top_result = await db.execute(
        select(BlogTopic.title, BlogTopic.priority_score)
        .where(
            BlogTopic.project_id == project_id,
            BlogTopic.tenant_id == tenant_id,
            BlogTopic.status.in_([BlogTopicStatus.suggested, BlogTopicStatus.approved]),
        )
        .order_by(BlogTopic.priority_score.desc())
        .limit(1)
    )
    top = top_result.first()

    profile = await WebsiteProfileService(db).get(project_id, tenant_id)

    return {
        "blogs_per_week": len(slots),
        "topics_waiting": topics_waiting,
        "drafts": drafts,
        "pending_approval": pending,
        "published": published,
        "refresh_pending": refresh_pending,
        "clusters": clusters,
        "cluster_gaps": cluster_gaps,
        "next_slot": (
            {
                "day": _DAYS[slots[0].day_of_week or 0],
                "next_run_at": slots[0].next_run_at.isoformat() if slots[0].next_run_at else None,
            }
            if slots
            else None
        ),
        "top_opportunity": (
            {"title": top[0], "opportunity_score": float(top[1] or 0)} if top else None
        ),
        "profile_available": profile is not None,
        # Never a zero. A score of 0 reads as "measured, and nobody cites you",
        # which is not what happened: nothing was measured at all.
        "ai_visibility": {
            "available": False,
            "reason": "AI citation measurement is not configured. AEO readiness is measured separately.",
        },
    }


@router.get("/projects/{project_id}/opportunities")
async def list_opportunities(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
):
    """Ranked topics, each carrying the reason it was chosen."""
    await _require_project(db, project_id, _tenant_id(current_user))
    from sqlalchemy import select

    from app.models.blog import BlogTopic, BlogTopicStatus

    result = await db.execute(
        select(BlogTopic)
        .where(
            BlogTopic.project_id == project_id,
            BlogTopic.tenant_id == _tenant_id(current_user),
            BlogTopic.status != BlogTopicStatus.rejected,
        )
        .order_by(BlogTopic.priority_score.desc())
        .limit(limit)
    )
    topics = list(result.scalars().all())

    def enum_value(value):
        return value.value if hasattr(value, "value") else value

    return {
        "topics": [
            {
                "id": str(t.id),
                "title": t.title,
                "target_keyword": t.target_keyword,
                "search_intent": enum_value(t.search_intent),
                # Named Opportunity Score, never "volume" — that distinction is
                # the entire point of the scoring model.
                "opportunity_score": float(t.priority_score or 0),
                "reason": t.reason,
                "status": enum_value(t.status),
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in topics
        ],
        "count": len(topics),
    }


@router.get("/projects/{project_id}/calendar")
async def content_calendar(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The drafting slots this project runs, and what each would write."""
    await _require_project(db, project_id, _tenant_id(current_user))
    from sqlalchemy import select

    from app.models.blog import BlogTopic, BlogTopicStatus
    from app.models.scheduler import SeoSchedule, SeoScheduleType

    tenant_id = _tenant_id(current_user)
    result = await db.execute(
        select(SeoSchedule)
        .where(
            SeoSchedule.project_id == project_id,
            SeoSchedule.tenant_id == tenant_id,
            SeoSchedule.schedule_type == SeoScheduleType.blog_generation,
        )
        .order_by(SeoSchedule.day_of_week)
    )
    slots = list(result.scalars().all())

    queued_result = await db.execute(
        select(BlogTopic.title)
        .where(
            BlogTopic.project_id == project_id,
            BlogTopic.tenant_id == tenant_id,
            BlogTopic.status.in_([BlogTopicStatus.approved, BlogTopicStatus.suggested]),
        )
        .order_by(BlogTopic.priority_score.desc())
        .limit(max(len(slots), 1))
    )
    queued = [row[0] for row in queued_result.all()]

    return {
        "blogs_per_week": len([s for s in slots if s.is_enabled]),
        "slots": [
            {
                "day": _DAYS[slot.day_of_week or 0],
                "day_of_week": slot.day_of_week or 0,
                "hour": slot.hour,
                "next_run_at": slot.next_run_at.isoformat() if slot.next_run_at else None,
                # What this slot would write if it ran now. None means it will
                # skip, which is a correct decision rather than a gap to fill.
                "topic": queued[index] if index < len(queued) else None,
                "status": "queued" if index < len(queued) else "will skip - nothing above the bar",
                "enabled": bool(slot.is_enabled),
            }
            for index, slot in enumerate(slots)
        ],
    }
