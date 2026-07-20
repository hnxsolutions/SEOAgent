"""
SEO Agent SaaS - Project Routes
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, List
from uuid import UUID

import structlog

from app.core.config import settings
from app.core.database import get_db
from app.jobs.seo_run_jobs import run_seo_run_background
from app.schemas.projects import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.projects import ProjectService
from app.services.seo_run import SeoRunService
from app.core.security import get_current_user

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create a new SEO project.

    Autonomy: unless disabled via AUTO_RUN_SEO_ON_PROJECT_CREATE, immediately
    start the full SEO pipeline in the background so analysis begins the moment a
    project exists. A failure to enqueue must never fail project creation.
    """
    project_service = ProjectService(db)
    project = await project_service.create_project(
        project_data,
        tenant_id=current_user["tenant_id"],
        user_id=current_user["user_id"]
    )

    if settings.AUTO_RUN_SEO_ON_PROJECT_CREATE:
        try:
            run = await SeoRunService(db).start_run(project.id, current_user["tenant_id"])
            from app.queue.client import enqueue_or_background

            enqueue_or_background(
                background_tasks, "app.queue.jobs.run_seo_run", run_seo_run_background,
                run.id, current_user["tenant_id"], max_retries=0,
            )
            logger.info(
                "auto_seo_run_enqueued_on_project_create",
                project_id=str(project.id),
                run_id=str(run.id),
            )
        except Exception:
            # Project creation must succeed even if the auto-run cannot start;
            # the user can still trigger a run manually from the dashboard.
            logger.exception(
                "auto_seo_run_enqueue_failed", project_id=str(project.id)
            )

    return project


@router.get("/", response_model=List[ProjectResponse])
async def list_projects(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """List all projects for current tenant"""
    project_service = ProjectService(db)
    projects = await project_service.get_tenant_projects(current_user["tenant_id"])
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get project details"""
    project_service = ProjectService(db)
    project = await project_service.get_project(project_id, current_user["tenant_id"])
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    project_data: ProjectUpdate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Update project"""
    project_service = ProjectService(db)
    project = await project_service.update_project(
        project_id,
        project_data,
        current_user["tenant_id"]
    )
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Delete project"""
    project_service = ProjectService(db)
    await project_service.delete_project(project_id, current_user["tenant_id"])
