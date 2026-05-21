"""Blog publishing, export, and infrastructure API routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.blog_publishing import BlogPublishProvider
from app.repo_agent.scanner import PathSafetyError
from app.schemas.blog_publishing import (
    BlogInfrastructureCheckRequest,
    BlogInfrastructureCheckResponse,
    BlogInfrastructurePatchRequest,
    BlogPublishActionResponse,
    BlogPublishConnectionCreate,
    BlogPublishConnectionListResponse,
    BlogPublishConnectionResponse,
    BlogPublishConnectionTestResponse,
    BlogPublishResultResponse,
    BlogPublishRunResponse,
    MarkdownExportRequest,
    NextJsBlogPatchRequest,
    WordPressDraftRequest,
)
from app.services.blog_publishing import BlogPublishingError, BlogPublishingService

router = APIRouter()


@router.post("/connections", response_model=BlogPublishConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_blog_publish_connection(
    payload: BlogPublishConnectionCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a draft-only publishing/export connection."""
    service = BlogPublishingService(db)
    try:
        return await service.create_connection(
            tenant_id=_tenant_id(current_user),
            project_id=payload.project_id,
            provider=payload.provider,
            site_url=payload.site_url,
            repo_connection_id=payload.repo_connection_id,
            export_folder_path=payload.export_folder_path,
            username=payload.username,
            app_password=payload.app_password,
            auto_upload_drafts_enabled=payload.auto_upload_drafts_enabled,
            auto_publish_enabled=payload.auto_publish_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/connections/projects/{project_id}", response_model=BlogPublishConnectionListResponse)
async def list_blog_publish_connections(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Optional[BlogPublishProvider] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List publishing/export connections for a project."""
    service = BlogPublishingService(db)
    connections = await service.list_connections(
        tenant_id=_tenant_id(current_user),
        project_id=project_id,
        provider=provider,
        limit=limit,
        offset=offset,
    )
    return BlogPublishConnectionListResponse(
        connections=connections,
        limit=limit,
        offset=offset,
        has_more=len(connections) == limit,
    )


@router.post("/connections/{connection_id}/test", response_model=BlogPublishConnectionTestResponse)
async def test_blog_publish_connection(
    connection_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = BlogPublishingService(db)
    try:
        return await service.test_connection(connection_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/projects/{project_id}/check-infrastructure", response_model=BlogInfrastructureCheckResponse)
async def check_blog_infrastructure(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: BlogInfrastructureCheckRequest = Body(default_factory=BlogInfrastructureCheckRequest),
):
    service = BlogPublishingService(db)
    try:
        return await service.check_infrastructure(
            tenant_id=_tenant_id(current_user),
            project_id=project_id,
            repo_connection_id=payload.repo_connection_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}/infrastructure", response_model=BlogInfrastructureCheckResponse)
async def get_latest_blog_infrastructure(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = BlogPublishingService(db)
    check = await service.latest_infrastructure(project_id, _tenant_id(current_user))
    if not check:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog infrastructure check not found")
    return check


@router.post("/drafts/{blog_draft_id}/export-markdown", response_model=BlogPublishActionResponse)
async def export_blog_draft_markdown(
    blog_draft_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: MarkdownExportRequest = Body(default_factory=MarkdownExportRequest),
):
    service = BlogPublishingService(db)
    try:
        run, result = await service.export_markdown(
            draft_id=blog_draft_id,
            tenant_id=_tenant_id(current_user),
            connection_id=payload.connection_id,
            export_folder_path=payload.export_folder_path,
            overwrite=payload.overwrite,
        )
        return BlogPublishActionResponse(run=run, result=result)
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except BlogPublishingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/drafts/{blog_draft_id}/create-wordpress-draft", response_model=BlogPublishActionResponse)
async def create_wordpress_blog_draft(
    blog_draft_id: UUID,
    payload: WordPressDraftRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = BlogPublishingService(db)
    try:
        run, result = await service.create_wordpress_draft(
            draft_id=blog_draft_id,
            tenant_id=_tenant_id(current_user),
            connection_id=payload.connection_id,
        )
        return BlogPublishActionResponse(run=run, result=result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except BlogPublishingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/drafts/{blog_draft_id}/create-nextjs-blog-patch", response_model=BlogPublishActionResponse)
async def create_nextjs_blog_patch(
    blog_draft_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: NextJsBlogPatchRequest = Body(default_factory=NextJsBlogPatchRequest),
):
    service = BlogPublishingService(db)
    try:
        run, result = await service.create_nextjs_blog_patch(
            draft_id=blog_draft_id,
            tenant_id=_tenant_id(current_user),
            connection_id=payload.connection_id,
            repo_connection_id=payload.repo_connection_id,
            content_directory=payload.content_directory,
            extension=payload.extension,
            overwrite=payload.overwrite,
        )
        return BlogPublishActionResponse(run=run, result=result)
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except BlogPublishingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/projects/{project_id}/create-blog-infrastructure-patch", response_model=BlogPublishActionResponse)
async def create_blog_infrastructure_patch(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: BlogInfrastructurePatchRequest = Body(default_factory=BlogInfrastructurePatchRequest),
):
    service = BlogPublishingService(db)
    try:
        run, result = await service.create_blog_infrastructure_patch(
            project_id=project_id,
            tenant_id=_tenant_id(current_user),
            connection_id=payload.connection_id,
            repo_connection_id=payload.repo_connection_id,
            strategy=payload.strategy,
        )
        return BlogPublishActionResponse(run=run, result=result)
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except BlogPublishingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/runs/{run_id}/status", response_model=BlogPublishRunResponse)
async def get_blog_publish_run_status(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = BlogPublishingService(db)
    run = await service.get_run(run_id, _tenant_id(current_user))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog publish run not found")
    return run


@router.get("/runs/{run_id}/result", response_model=BlogPublishResultResponse)
async def get_blog_publish_run_result(
    run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = BlogPublishingService(db)
    result = await service.get_result(run_id, _tenant_id(current_user))
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog publish result not found")
    return result


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
