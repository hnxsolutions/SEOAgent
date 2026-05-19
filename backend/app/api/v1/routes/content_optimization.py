"""Content optimization suggestion API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.models.content_optimization import (
    ContentOptimizationSuggestionStatus,
    ContentOptimizationSuggestionType,
)
from app.schemas.content_optimization import (
    ContentOptimizationRunResponse,
    ContentOptimizationSuggestionListResponse,
    ContentOptimizationSuggestionResponse,
    ContentOptimizationSummaryResponse,
)
from app.services.content_optimization import ContentOptimizationService
from app.services.local_llm import LocalLLMError

router = APIRouter()


@router.post(
    "/crawls/{crawl_id}/generate",
    response_model=ContentOptimizationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_content_optimization(
    crawl_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start local-LLM page-level content optimization suggestions for a crawl."""
    service = ContentOptimizationService(db)
    try:
        run = await service.start_generation(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    background_tasks.add_task(run_content_optimization_background, run.id)
    return run


@router.get("/runs/{run_id}/status", response_model=ContentOptimizationRunResponse)
async def get_content_optimization_run_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get content optimization run status."""
    service = ContentOptimizationService(db)
    run = await service.get_run_status(run_id, current_user["tenant_id"])
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content optimization run not found")
    return run


@router.get("/crawls/{crawl_id}/suggestions", response_model=ContentOptimizationSuggestionListResponse)
async def list_crawl_content_suggestions(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    suggestion_status: Optional[ContentOptimizationSuggestionStatus] = Query(None, alias="status"),
    suggestion_type: Optional[ContentOptimizationSuggestionType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List content optimization suggestions for a crawl."""
    service = ContentOptimizationService(db)
    suggestions = await service.list_suggestions(
        tenant_id=current_user["tenant_id"],
        crawl_id=crawl_id,
        status=suggestion_status,
        suggestion_type=suggestion_type,
        limit=limit,
        offset=offset,
    )
    return ContentOptimizationSuggestionListResponse(
        suggestions=suggestions,
        limit=limit,
        offset=offset,
        has_more=len(suggestions) == limit,
    )


@router.get("/pages/{page_id}/suggestions", response_model=ContentOptimizationSuggestionListResponse)
async def list_page_content_suggestions(
    page_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    suggestion_status: Optional[ContentOptimizationSuggestionStatus] = Query(None, alias="status"),
    suggestion_type: Optional[ContentOptimizationSuggestionType] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List content optimization suggestions for one page."""
    service = ContentOptimizationService(db)
    suggestions = await service.list_suggestions(
        tenant_id=current_user["tenant_id"],
        page_id=page_id,
        status=suggestion_status,
        suggestion_type=suggestion_type,
        limit=limit,
        offset=offset,
    )
    return ContentOptimizationSuggestionListResponse(
        suggestions=suggestions,
        limit=limit,
        offset=offset,
        has_more=len(suggestions) == limit,
    )


@router.post("/suggestions/{suggestion_id}/approve", response_model=ContentOptimizationSuggestionResponse)
async def approve_content_suggestion(
    suggestion_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_status(suggestion_id, current_user["tenant_id"], db, ContentOptimizationSuggestionStatus.approved)


@router.post("/suggestions/{suggestion_id}/reject", response_model=ContentOptimizationSuggestionResponse)
async def reject_content_suggestion(
    suggestion_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_status(suggestion_id, current_user["tenant_id"], db, ContentOptimizationSuggestionStatus.rejected)


@router.post("/suggestions/{suggestion_id}/mark-applied", response_model=ContentOptimizationSuggestionResponse)
async def mark_content_suggestion_applied(
    suggestion_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_status(suggestion_id, current_user["tenant_id"], db, ContentOptimizationSuggestionStatus.applied)


@router.get("/crawls/{crawl_id}/summary", response_model=ContentOptimizationSummaryResponse)
async def get_content_optimization_summary(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get content optimization suggestion summary for a crawl."""
    service = ContentOptimizationService(db)
    try:
        return await service.summary(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def _set_status(
    suggestion_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
    suggestion_status: ContentOptimizationSuggestionStatus,
):
    service = ContentOptimizationService(db)
    try:
        return await service.update_status(suggestion_id, tenant_id, suggestion_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def run_content_optimization_background(run_id: UUID) -> None:
    """Execute content optimization with a fresh DB session."""
    db = get_db_session()
    try:
        service = ContentOptimizationService(db)
        await service.execute_generation(run_id)
    except LocalLLMError:
        raise
    finally:
        await db.close()
