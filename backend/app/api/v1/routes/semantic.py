"""Local semantic SEO API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.schemas.semantic import (
    SemanticClustersResponse,
    SemanticIndexRunResponse,
    SemanticSearchResponse,
    SemanticSimilarPagesResponse,
)
from app.services.semantic import SemanticService

router = APIRouter()


@router.post(
    "/crawls/{crawl_id}/index",
    response_model=SemanticIndexRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_semantic_index(
    crawl_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start local semantic indexing for an existing crawl."""
    service = SemanticService(db)
    try:
        run = await service.start_index(crawl_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    background_tasks.add_task(run_semantic_index_background, run.id)
    return run


@router.get("/index-runs/{run_id}/status", response_model=SemanticIndexRunResponse)
async def get_semantic_index_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get semantic indexing run status."""
    service = SemanticService(db)
    run = await service.get_index_status(run_id, current_user["tenant_id"])
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Semantic index run not found")
    return run


@router.get("/search", response_model=SemanticSearchResponse)
async def semantic_search(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: str = Query(..., min_length=1),
    project_id: Optional[UUID] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Search locally indexed semantic content."""
    service = SemanticService(db)
    try:
        results = await service.search(
            tenant_id=current_user["tenant_id"],
            project_id=project_id,
            query=query,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return SemanticSearchResponse(query=query, results=results, limit=limit)


@router.get("/pages/{page_id}/similar", response_model=SemanticSimilarPagesResponse)
async def get_similar_pages(
    page_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(10, ge=1, le=50),
):
    """Find semantically similar pages using local Qdrant vectors."""
    service = SemanticService(db)
    try:
        results = await service.similar_pages(page_id, current_user["tenant_id"], limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return SemanticSimilarPagesResponse(page_id=page_id, results=results, limit=limit)


@router.get("/crawls/{crawl_id}/clusters", response_model=SemanticClustersResponse)
async def get_crawl_semantic_clusters(
    crawl_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(500, ge=1, le=1000),
):
    """Return lightweight semantic page clusters for a crawl."""
    service = SemanticService(db)
    try:
        clusters = await service.crawl_clusters(crawl_id, current_user["tenant_id"], limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return SemanticClustersResponse(crawl_id=crawl_id, clusters=clusters, limit=limit)


async def run_semantic_index_background(run_id: UUID) -> None:
    """Execute semantic indexing with a fresh DB session."""
    db = get_db_session()
    try:
        service = SemanticService(db)
        await service.execute_index(run_id)
    finally:
        await db.close()
