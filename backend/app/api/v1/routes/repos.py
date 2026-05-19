"""Review-only SEO code repository agent routes."""
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.repo_agent import SeoCodeIssueStatus, SeoCodePatchStatus
from app.repo_agent.scanner import PathSafetyError
from app.schemas.repo_agent import (
    PatchApplyRequest,
    PatchApplyResultListResponse,
    PatchApplyRunResponse,
    PullRequestCreateRequest,
    PullRequestRecordResponse,
    RepoConnectionCreate,
    RepoConnectionListResponse,
    RepoConnectionResponse,
    RepoFileListResponse,
    RepoScanRunResponse,
    SeoCodeIssueListResponse,
    SeoCodePatchGenerateResponse,
    SeoCodePatchListResponse,
    SeoCodePatchResponse,
)
from app.services.repo_agent import RepoAgentError, RepoAgentService

router = APIRouter()


@router.post("/connections", response_model=RepoConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_repo_connection(
    payload: RepoConnectionCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Create a local or GitHub metadata repository connection."""
    service = RepoAgentService(db)
    try:
        return await service.create_connection(
            tenant_id=_tenant_id(current_user),
            project_id=payload.project_id,
            provider=payload.provider,
            repo_url=payload.repo_url,
            local_path=payload.local_path,
            default_branch=payload.default_branch,
            framework=payload.framework,
        )
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/connections", response_model=RepoConnectionListResponse)
async def list_repo_connections(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List repository connections."""
    service = RepoAgentService(db)
    connections = await service.list_connections(
        tenant_id=_tenant_id(current_user),
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return RepoConnectionListResponse(connections=connections, limit=limit, offset=offset, has_more=len(connections) == limit)


@router.get("/connections/{connection_id}", response_model=RepoConnectionResponse)
async def get_repo_connection(
    connection_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get one repository connection."""
    service = RepoAgentService(db)
    connection = await service.get_connection(connection_id, _tenant_id(current_user))
    if not connection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository connection not found")
    return connection


@router.post("/connections/{connection_id}/scan", response_model=RepoScanRunResponse)
async def scan_repo_connection(
    connection_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run a local repository scan now."""
    service = RepoAgentService(db)
    try:
        return await service.scan_connection(connection_id, _tenant_id(current_user))
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RepoAgentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/scans/{scan_id}/status", response_model=RepoScanRunResponse)
async def get_repo_scan_status(
    scan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get repository scan status."""
    service = RepoAgentService(db)
    run = await service.get_scan_status(scan_id, _tenant_id(current_user))
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository scan not found")
    return run


@router.get("/scans/{scan_id}/files", response_model=RepoFileListResponse)
async def list_repo_scan_files(
    scan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List files discovered by a scan."""
    service = RepoAgentService(db)
    files = await service.list_files(scan_id, _tenant_id(current_user), limit=limit, offset=offset)
    return RepoFileListResponse(files=files, limit=limit, offset=offset, has_more=len(files) == limit)


@router.get("/scans/{scan_id}/issues", response_model=SeoCodeIssueListResponse)
async def list_repo_scan_issues(
    scan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    issue_status: Optional[SeoCodeIssueStatus] = Query(None, alias="status"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List SEO code issues created by a scan."""
    service = RepoAgentService(db)
    issues = await service.list_issues(
        scan_id,
        _tenant_id(current_user),
        status=issue_status,
        limit=limit,
        offset=offset,
    )
    return SeoCodeIssueListResponse(issues=issues, limit=limit, offset=offset, has_more=len(issues) == limit)


@router.post("/scans/{scan_id}/patches/generate", response_model=SeoCodePatchGenerateResponse)
async def generate_repo_scan_patches(
    scan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Generate reviewable SEO-only patch records for open issues."""
    service = RepoAgentService(db)
    try:
        patches = await service.generate_patches(scan_id, _tenant_id(current_user))
        return SeoCodePatchGenerateResponse(scan_id=scan_id, patches_created=len(patches), patches=patches)
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/scans/{scan_id}/patches", response_model=SeoCodePatchListResponse)
async def list_repo_scan_patches(
    scan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    patch_status: Optional[SeoCodePatchStatus] = Query(None, alias="status"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List reviewable patches for a scan."""
    service = RepoAgentService(db)
    patches = await service.list_patches(
        scan_id,
        _tenant_id(current_user),
        status=patch_status,
        limit=limit,
        offset=offset,
    )
    return SeoCodePatchListResponse(patches=patches, limit=limit, offset=offset, has_more=len(patches) == limit)


@router.get("/patches/{patch_id}", response_model=SeoCodePatchResponse)
async def get_repo_patch(
    patch_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a reviewable SEO code patch."""
    service = RepoAgentService(db)
    patch = await service.get_patch(patch_id, _tenant_id(current_user))
    if not patch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SEO code patch not found")
    return patch


@router.post("/patches/{patch_id}/approve", response_model=SeoCodePatchResponse)
async def approve_repo_patch(
    patch_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_patch_status(patch_id, current_user, db, SeoCodePatchStatus.approved)


@router.post("/patches/{patch_id}/reject", response_model=SeoCodePatchResponse)
async def reject_repo_patch(
    patch_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_patch_status(patch_id, current_user, db, SeoCodePatchStatus.rejected)


@router.post("/patches/{patch_id}/mark-applied", response_model=SeoCodePatchResponse)
async def mark_repo_patch_applied(
    patch_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _set_patch_status(patch_id, current_user, db, SeoCodePatchStatus.applied)


@router.post("/scans/{scan_id}/apply-approved-patches", response_model=PatchApplyRunResponse)
async def apply_repo_scan_approved_patches(
    scan_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: PatchApplyRequest = Body(default_factory=PatchApplyRequest),
):
    """Apply approved SEO code patches to a controlled local git branch."""
    service = RepoAgentService(db)
    try:
        return await service.apply_approved_patches(
            scan_id,
            _tenant_id(current_user),
            allow_high_risk=payload.allow_high_risk,
            run_validation=payload.run_validation,
            validation_commands=payload.validation_commands,
        )
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RepoAgentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/apply-runs/{apply_run_id}/status", response_model=PatchApplyRunResponse)
async def get_repo_apply_run_status(
    apply_run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = RepoAgentService(db)
    apply_run = await service.get_apply_run_status(apply_run_id, _tenant_id(current_user))
    if not apply_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patch apply run not found")
    return apply_run


@router.get("/apply-runs/{apply_run_id}/results", response_model=PatchApplyResultListResponse)
async def list_repo_apply_run_results(
    apply_run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    service = RepoAgentService(db)
    try:
        results = await service.list_apply_results(apply_run_id, _tenant_id(current_user), limit=limit, offset=offset)
        return PatchApplyResultListResponse(results=results, limit=limit, offset=offset, has_more=len(results) == limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/apply-runs/{apply_run_id}/create-pr", response_model=PullRequestRecordResponse)
async def create_repo_apply_run_pull_request(
    apply_run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: PullRequestCreateRequest = Body(default_factory=PullRequestCreateRequest),
):
    service = RepoAgentService(db)
    try:
        return await service.create_pull_request(
            apply_run_id,
            _tenant_id(current_user),
            force_pr_on_validation_failure=payload.force_pr_on_validation_failure,
            draft=payload.draft,
            title=payload.title,
            description=payload.description,
        )
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/pull-requests/{pr_id}", response_model=PullRequestRecordResponse)
async def get_repo_pull_request(
    pr_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = RepoAgentService(db)
    record = await service.get_pull_request(pr_id, _tenant_id(current_user))
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pull request record not found")
    return record


@router.post("/apply-runs/{apply_run_id}/rollback", response_model=PatchApplyRunResponse)
async def rollback_repo_apply_run(
    apply_run_id: UUID,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    service = RepoAgentService(db)
    try:
        return await service.rollback_apply_run(apply_run_id, _tenant_id(current_user))
    except PathSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def _set_patch_status(patch_id: UUID, current_user: dict, db: AsyncSession, patch_status: SeoCodePatchStatus):
    service = RepoAgentService(db)
    try:
        return await service.update_patch_status(patch_id, _tenant_id(current_user), patch_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _tenant_id(current_user: dict) -> UUID:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Authenticated user has no tenant context")
    return tenant_id
