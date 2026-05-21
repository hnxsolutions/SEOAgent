"""SEO copy quality and compliance review routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.copy_review import SeoCopyApprovalReadiness
from app.schemas.copy_review import (
    SeoCopyPolicyRequest,
    SeoCopyPolicyResponse,
    SeoCopyReviewListResponse,
    SeoCopyReviewRequest,
    SeoCopyReviewResponse,
    SeoCopyReviewResult,
)
from app.services.copy_review import SeoCopyReviewService

router = APIRouter()


@router.post("/review", response_model=SeoCopyReviewResult, status_code=status.HTTP_201_CREATED)
async def review_copy(
    payload: SeoCopyReviewRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoCopyReviewService(db)
    try:
        if payload.source_type.value == "repo_patch" and payload.source_reference_id:
            return await service.review_repo_patch(
                payload.source_reference_id,
                _tenant_id(current_user),
                compliance_profile=payload.compliance_profile,
                apply_revision=payload.apply_revision,
            )
        return await service.review_copy(
            tenant_id=_tenant_id(current_user),
            project_id=payload.project_id,
            source_type=payload.source_type,
            source_reference_id=payload.source_reference_id,
            page_url=payload.page_url,
            target_keyword=payload.target_keyword,
            original_title=payload.original_title,
            original_description=payload.original_description,
            compliance_profile=payload.compliance_profile,
            apply_revision=payload.apply_revision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/policies", response_model=SeoCopyPolicyResponse, status_code=status.HTTP_201_CREATED)
async def upsert_copy_policy(
    payload: SeoCopyPolicyRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoCopyReviewService(db)
    project = await service.repository.get_project(payload.project_id, _tenant_id(current_user))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    policy = await service.repository.upsert_policy(
        tenant_id=_tenant_id(current_user),
        project_id=payload.project_id,
        compliance_profile=payload.compliance_profile,
        blocked_phrases=payload.blocked_phrases,
        allowed_topics=payload.allowed_topics,
        notes=payload.notes,
    )
    await db.commit()
    await db.refresh(policy)
    return policy


@router.get("/projects/{project_id}/reviews", response_model=SeoCopyReviewListResponse)
async def list_copy_reviews(
    project_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    readiness: Optional[SeoCopyApprovalReadiness] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    service = SeoCopyReviewService(db)
    try:
        reviews = await service.list_reviews(project_id, _tenant_id(current_user), readiness=readiness, limit=limit, offset=offset)
        return SeoCopyReviewListResponse(reviews=reviews, limit=limit, offset=offset, has_more=len(reviews) == limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/reviews/{review_id}", response_model=SeoCopyReviewResponse)
async def get_copy_review(
    review_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoCopyReviewService(db)
    review = await service.get_review(review_id, _tenant_id(current_user))
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO copy review not found")
    return review


@router.post("/reviews/{review_id}/accept-revision", response_model=SeoCopyReviewResult)
async def accept_copy_revision(
    review_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoCopyReviewService(db)
    try:
        return await service.accept_revision(review_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/reviews/{review_id}/reject-revision", response_model=SeoCopyReviewResult)
async def reject_copy_revision(
    review_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = SeoCopyReviewService(db)
    try:
        return await service.reject_revision(review_id, _tenant_id(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
