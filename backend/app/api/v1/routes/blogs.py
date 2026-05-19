"""Blog planner and draft API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.blog import BlogPlanStatus, BlogTopicStatus
from app.schemas.blogs import (
    BlogDraftListResponse,
    BlogDraftResponse,
    BlogPlanCreate,
    BlogPlanListResponse,
    BlogPlanResponse,
    BlogTopicGenerateRequest,
    BlogTopicListResponse,
    BlogTopicResponse,
)
from app.services.blogs import BlogService

router = APIRouter()


@router.post("/plans", response_model=BlogPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_blog_plan(
    payload: BlogPlanCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a buyer-intent blog plan."""
    service = BlogService(db)
    try:
        return await service.create_plan(
            tenant_id=current_user["tenant_id"],
            project_id=payload.project_id,
            title=payload.title,
            description=payload.description,
            target_site_url=payload.target_site_url,
            blogs_per_week=payload.blogs_per_week,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/plans", response_model=BlogPlanListResponse)
async def list_blog_plans(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    plan_status: Optional[BlogPlanStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List blog plans."""
    service = BlogService(db)
    plans = await service.list_plans(
        tenant_id=current_user["tenant_id"],
        project_id=project_id,
        status=plan_status,
        limit=limit,
        offset=offset,
    )
    return BlogPlanListResponse(plans=plans, limit=limit, offset=offset, has_more=len(plans) == limit)


@router.get("/plans/{plan_id}", response_model=BlogPlanResponse)
async def get_blog_plan(
    plan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get one blog plan."""
    service = BlogService(db)
    plan = await service.get_plan(plan_id, current_user["tenant_id"])
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog plan not found")
    return plan


@router.post("/plans/{plan_id}/topics/generate", response_model=BlogTopicListResponse)
async def generate_blog_topics(
    plan_id: UUID,
    payload: BlogTopicGenerateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate buyer-intent blog topics for a plan."""
    service = BlogService(db)
    try:
        topics = await service.generate_topics(plan_id, current_user["tenant_id"], count=payload.count)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return BlogTopicListResponse(topics=topics, limit=len(topics), offset=0, has_more=False)


@router.get("/plans/{plan_id}/topics", response_model=BlogTopicListResponse)
async def list_blog_topics(
    plan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    topic_status: Optional[BlogTopicStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List topics for a blog plan."""
    service = BlogService(db)
    try:
        topics = await service.list_topics(
            plan_id=plan_id,
            tenant_id=current_user["tenant_id"],
            status=topic_status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return BlogTopicListResponse(topics=topics, limit=limit, offset=offset, has_more=len(topics) == limit)


@router.post("/topics/{topic_id}/approve", response_model=BlogTopicResponse)
async def approve_blog_topic(
    topic_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_topic_status(topic_id, current_user["tenant_id"], db, BlogTopicStatus.approved)


@router.post("/topics/{topic_id}/reject", response_model=BlogTopicResponse)
async def reject_blog_topic(
    topic_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_topic_status(topic_id, current_user["tenant_id"], db, BlogTopicStatus.rejected)


@router.post("/topics/{topic_id}/draft", response_model=BlogDraftResponse, status_code=status.HTTP_201_CREATED)
async def draft_blog_topic(
    topic_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate a markdown blog draft for an approved topic."""
    service = BlogService(db)
    try:
        return await service.draft_topic(topic_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/drafts/{draft_id}", response_model=BlogDraftResponse)
async def get_blog_draft(
    draft_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a blog draft."""
    service = BlogService(db)
    draft = await service.get_draft(draft_id, current_user["tenant_id"])
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog draft not found")
    return draft


@router.get("/plans/{plan_id}/drafts", response_model=BlogDraftListResponse)
async def list_blog_drafts_for_plan(
    plan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List drafts for a blog plan."""
    service = BlogService(db)
    try:
        drafts = await service.list_drafts_for_plan(plan_id, current_user["tenant_id"], limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return BlogDraftListResponse(drafts=drafts, limit=limit, offset=offset, has_more=len(drafts) == limit)


async def _set_topic_status(topic_id: UUID, tenant_id: UUID, db: AsyncSession, topic_status: BlogTopicStatus):
    service = BlogService(db)
    try:
        return await service.update_topic_status(topic_id, tenant_id, topic_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
