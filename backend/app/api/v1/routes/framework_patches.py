"""Framework-aware SEO patch generator routes.

Generate real, SEO-safe, framework-native code patches for a project's detected
stack (metadata / robots / sitemap / schema / Open Graph). List and inspect them
for review before opening a PR. Credential-free; degrades gracefully when the
technology hasn't been analyzed or the framework has no dedicated generator.
"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.framework_patch_generator import FrameworkPatchGeneratorService

router = APIRouter()


def _tenant_id(u: dict) -> UUID:
    return u["tenant_id"]


class GenerateRequest(BaseModel):
    surfaces: Optional[List[str]] = None  # subset of metadata/robots/sitemap/schema/og_twitter


class GeneratedPatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    project_id: UUID
    framework: str
    surface: str
    patch_type: str
    target_file: str
    language: Optional[str] = None
    generated_code: str
    is_new_file: Optional[bool] = None
    code_fixable: Optional[bool] = None
    explanation: Optional[str] = None
    notes: Optional[str] = None
    safe: Optional[bool] = None
    safety_reason: Optional[str] = None
    validation_status: str
    validation_notes: Optional[Dict[str, Any]] = None
    seo_before: Optional[int] = None
    seo_after: Optional[int] = None
    performance_before: Optional[int] = None
    ready_for_pr: Optional[bool] = None
    confidence: Optional[int] = None
    created_at: Optional[datetime] = None


@router.post("/projects/{project_id}/generate")
async def generate_patches(
    project_id: UUID,
    payload: GenerateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    try:
        return await FrameworkPatchGeneratorService(db).generate(
            project_id, _tenant_id(current_user), surfaces=payload.surfaces
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/projects/{project_id}")
async def list_patches(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    items = await FrameworkPatchGeneratorService(db).list_patches(project_id, _tenant_id(current_user))
    return {"items": [GeneratedPatchResponse.model_validate(i) for i in items], "total": len(items)}


@router.get("/projects/{project_id}/summary")
async def patches_summary(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    return await FrameworkPatchGeneratorService(db).summary(project_id, _tenant_id(current_user))


@router.get("/{patch_id}", response_model=GeneratedPatchResponse)
async def get_patch(
    patch_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    patch = await FrameworkPatchGeneratorService(db).get_patch(patch_id, _tenant_id(current_user))
    if not patch:
        raise HTTPException(status_code=404, detail="Patch not found")
    return patch
