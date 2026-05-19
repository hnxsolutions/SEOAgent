"""Knowledge base / local RAG API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, get_db_session
from app.core.security import get_current_user
from app.models.knowledge import KnowledgeSourceStatus, KnowledgeSourceType
from app.schemas.knowledge import (
    KnowledgeDocumentListResponse,
    KnowledgeIndexRunResponse,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceListResponse,
    KnowledgeSourceResponse,
    RelevantKnowledgeResponse,
)
from app.services.knowledge import KnowledgeService

router = APIRouter()


@router.post("/sources", response_model=KnowledgeSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_source(
    payload: KnowledgeSourceCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a manual knowledge source and its first text document."""
    service = KnowledgeService(db)
    try:
        return await service.create_source(
            tenant_id=current_user["tenant_id"],
            project_id=payload.project_id,
            source_type=payload.source_type,
            title=payload.title,
            description=payload.description,
            content=payload.content,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/sources", response_model=KnowledgeSourceListResponse)
async def list_knowledge_sources(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    source_type: Optional[KnowledgeSourceType] = Query(None),
    source_status: Optional[KnowledgeSourceStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List knowledge sources for the current tenant."""
    service = KnowledgeService(db)
    sources = await service.list_sources(
        tenant_id=current_user["tenant_id"],
        project_id=project_id,
        source_type=source_type,
        status=source_status,
        limit=limit,
        offset=offset,
    )
    return KnowledgeSourceListResponse(sources=sources, limit=limit, offset=offset, has_more=len(sources) == limit)


@router.get("/sources/{source_id}", response_model=KnowledgeSourceResponse)
async def get_knowledge_source(
    source_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get one knowledge source."""
    service = KnowledgeService(db)
    source = await service.get_source(source_id, current_user["tenant_id"])
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    return source


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_knowledge_documents(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    source_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List normalized knowledge documents."""
    service = KnowledgeService(db)
    documents = await service.list_documents(
        tenant_id=current_user["tenant_id"],
        project_id=project_id,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return KnowledgeDocumentListResponse(
        documents=documents,
        limit=limit,
        offset=offset,
        has_more=len(documents) == limit,
    )


@router.post(
    "/sources/{source_id}/index",
    response_model=KnowledgeIndexRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def index_knowledge_source(
    source_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start local embedding + Qdrant indexing for a knowledge source."""
    service = KnowledgeService(db)
    try:
        run = await service.start_index(source_id, current_user["tenant_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    background_tasks.add_task(run_knowledge_index_background, run.id)
    return run


@router.get("/index-runs/{run_id}/status", response_model=KnowledgeIndexRunResponse)
async def get_knowledge_index_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get knowledge index run status."""
    service = KnowledgeService(db)
    run = await service.get_index_status(run_id, current_user["tenant_id"])
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge index run not found")
    return run


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: str = Query(..., min_length=1),
    project_id: Optional[UUID] = Query(None),
    source_id: Optional[UUID] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Search user-provided knowledge with local embeddings and Qdrant."""
    service = KnowledgeService(db)
    try:
        results = await service.search(
            tenant_id=current_user["tenant_id"],
            project_id=project_id,
            source_id=source_id,
            query=query,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return KnowledgeSearchResponse(query=query, project_id=project_id, source_id=source_id, results=results, limit=limit)


@router.get("/relevant", response_model=RelevantKnowledgeResponse)
async def retrieve_relevant_knowledge(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    topic: str = Query(..., min_length=1),
    project_id: Optional[UUID] = Query(None),
    page_id: Optional[UUID] = Query(None),
    limit: int = Query(8, ge=1, le=50),
):
    """Retrieve knowledge chunks relevant to a keyword, page, or blog topic."""
    service = KnowledgeService(db)
    try:
        return await service.relevant_knowledge(
            tenant_id=current_user["tenant_id"],
            project_id=project_id,
            topic=topic,
            page_id=page_id,
            limit=limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


async def run_knowledge_index_background(run_id: UUID) -> None:
    """Execute knowledge indexing with a fresh DB session."""
    db = get_db_session()
    try:
        service = KnowledgeService(db)
        await service.execute_index(run_id)
    finally:
        await db.close()
