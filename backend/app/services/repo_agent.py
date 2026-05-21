"""GitHub SEO Code Agent foundation: local scans and reviewable patches."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.repo_agent import (
    PatchApplyResultStatus,
    PatchApplyRun,
    PatchApplyRunStatus,
    PatchValidationStatus,
    PullRequestRecord,
    PullRequestStatus,
    RepoConnection,
    RepoConnectionStatus,
    RepoFilePurpose,
    RepoProvider,
    RepoScanRun,
    RepoScanRunStatus,
    SeoCodeIssue,
    SeoCodeIssueSeverity,
    SeoCodeIssueSource,
    SeoCodeIssueStatus,
    SeoCodeIssueType,
    SeoCodePatch,
    SeoCodePatchRisk,
    SeoCodePatchStatus,
    SeoCodePatchType,
)
from app.repo_agent.git_ops import GitCommandRunner, GitHubClient, GitHubClientError, GitCommandError, ValidationRunner
from app.models.search_console import SearchConsoleOpportunityType
from app.repo_agent.architecture import (
    ArchitectureProfileData,
    RepoArchitectureDetector,
    html_metadata_patch_content,
)
from app.repo_agent.scanner import (
    IGNORE_DIRS,
    MAX_FILE_SIZE_BYTES,
    NextJsRepoScanner,
    PathSafetyError,
    RepoIssueCandidate,
    build_unified_diff,
    content_hash,
    is_client_component,
    label_from_route,
    metadata_patch_content,
    read_repo_text,
    resolve_repo_root,
    robots_patch_content,
    safe_child_path,
    schema_patch_content,
    sitemap_patch_content,
    static_routes_from_pages,
)
from app.repositories.repo_agent import RepoAgentRepository

logger = structlog.get_logger(__name__)


class RepoAgentError(RuntimeError):
    """Base repo-agent service error."""


class RepoAgentService:
    """Service for local repository scanning and SEO-only patch proposals."""

    def __init__(
        self,
        db: AsyncSession,
        scanner: Optional[NextJsRepoScanner] = None,
        git_runner: Optional[GitCommandRunner] = None,
        validation_runner: Optional[ValidationRunner] = None,
        github_client: Optional[GitHubClient] = None,
    ):
        self.db = db
        self.repository = RepoAgentRepository(db)
        self.scanner = scanner or NextJsRepoScanner()
        self.architecture_detector = RepoArchitectureDetector()
        self.git_runner = git_runner or GitCommandRunner(settings.REPO_AGENT_GIT_COMMAND_TIMEOUT_SECONDS)
        self.validation_runner = validation_runner or ValidationRunner(settings.REPO_AGENT_GIT_COMMAND_TIMEOUT_SECONDS)
        self.github_client = github_client or GitHubClient()

    async def create_connection(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        provider: RepoProvider,
        repo_url: Optional[str] = None,
        local_path: Optional[str] = None,
        default_branch: Optional[str] = None,
        framework: Optional[str] = None,
    ) -> RepoConnection:
        if project_id and not await self.repository.get_project(project_id, tenant_id):
            raise ValueError("Project not found")
        status = RepoConnectionStatus.connected
        detected_framework = framework
        clean_local_path = None
        if provider == RepoProvider.local:
            root = resolve_repo_root(local_path or "")
            clean_local_path = str(root)
            detected_framework = detected_framework or self.scanner.detect_framework(root)
        elif local_path:
            root = resolve_repo_root(local_path)
            clean_local_path = str(root)
            detected_framework = detected_framework or self.scanner.detect_framework(root)
        elif provider == RepoProvider.github:
            status = RepoConnectionStatus.unavailable
        connection = await self.repository.create_connection(
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
            repo_url=repo_url,
            local_path=clean_local_path,
            default_branch=default_branch,
            framework=detected_framework,
            status=status,
        )
        await self.db.commit()
        await self.db.refresh(connection)
        return connection

    async def list_connections(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[RepoConnection]:
        return await self.repository.list_connections(tenant_id, project_id=project_id, limit=limit, offset=offset)

    async def get_connection(self, connection_id: UUID, tenant_id: UUID) -> Optional[RepoConnection]:
        return await self.repository.get_connection(connection_id, tenant_id)

    async def start_scan(self, connection_id: UUID, tenant_id: UUID) -> RepoScanRun:
        connection = await self.repository.get_connection(connection_id, tenant_id)
        if not connection:
            raise ValueError("Repository connection not found")
        run = await self.repository.create_scan_run(connection)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def execute_scan(self, scan_id: UUID, tenant_id: Optional[UUID] = None) -> RepoScanRun:
        run = await self.repository.get_scan_run(scan_id, tenant_id=tenant_id)
        if not run:
            raise ValueError("Repository scan not found")
        connection = await self.repository.get_connection(run.repo_connection_id, run.tenant_id)
        if not connection:
            raise ValueError("Repository connection not found")
        await self.repository.set_scan_status(run, RepoScanRunStatus.running)
        await self.db.commit()
        try:
            if not connection.local_path:
                raise RepoAgentError("Local path scanning is required in this phase. GitHub API scanning is scaffolded only.")
            root = resolve_repo_root(connection.local_path)
            architecture_data = self.architecture_detector.detect(root)
            framework = architecture_data.detected_stack or self.scanner.detect_framework(root)
            scanned_files = self._merge_scanned_files(
                self.scanner.discover_files(root),
                self._architecture_scanned_files(root, architecture_data),
            )
            files = await self.repository.add_files(
                [
                    {
                        "tenant_id": run.tenant_id,
                        "project_id": run.project_id,
                        "repo_connection_id": run.repo_connection_id,
                        "scan_run_id": run.id,
                        "file_path": file.file_path,
                        "file_type": file.file_type,
                        "content_hash": file.content_hash,
                        "detected_purpose": file.detected_purpose,
                        "has_metadata": file.has_metadata,
                        "has_jsonld": file.has_jsonld,
                        "has_canonical": file.has_canonical,
                        "has_open_graph": file.has_open_graph,
                        "has_twitter_meta": file.has_twitter_meta,
                        "has_sitemap": file.has_sitemap,
                        "has_robots": file.has_robots,
                    }
                    for file in scanned_files
                ]
            )
            await self.repository.create_architecture_profile(run, architecture_data.as_record())
            file_by_path = {file.file_path: file for file in files}
            scanned_by_path = {file.file_path: file for file in scanned_files}
            candidates = self.scanner.analyze(scanned_files)
            candidates.extend(self._architecture_issue_candidates(architecture_data, scanned_by_path, file_by_path))
            candidates.extend(await self._signal_issue_candidates(run, scanned_files, file_by_path))
            issues = await self.repository.add_issues(
                [self._issue_record(run, candidate, file_by_path) for candidate in candidates]
            )
            await self.repository.finish_scan(run, framework, len(files), len(issues))
            await self.repository.set_connection_status(connection, RepoConnectionStatus.connected, framework=framework)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info("Completed repository scan", scan_id=str(run.id), files=len(files), issues=len(issues))
            return run
        except Exception as exc:
            await self.repository.set_scan_status(run, RepoScanRunStatus.failed, error_message=str(exc))
            await self.repository.set_connection_status(connection, RepoConnectionStatus.failed)
            await self.db.commit()
            logger.error("Repository scan failed", scan_id=str(run.id), error=str(exc), exc_info=True)
            raise

    async def scan_connection(self, connection_id: UUID, tenant_id: UUID) -> RepoScanRun:
        run = await self.start_scan(connection_id, tenant_id)
        return await self.execute_scan(run.id, tenant_id)

    async def get_scan_status(self, scan_id: UUID, tenant_id: UUID) -> Optional[RepoScanRun]:
        return await self.repository.get_scan_run(scan_id, tenant_id)

    async def list_files(self, scan_id: UUID, tenant_id: UUID, limit: int = 500, offset: int = 0):
        return await self.repository.list_files(scan_id, tenant_id, limit=limit, offset=offset)

    async def list_issues(
        self,
        scan_id: UUID,
        tenant_id: UUID,
        status: Optional[SeoCodeIssueStatus] = None,
        limit: int = 500,
        offset: int = 0,
    ):
        return await self.repository.list_issues(scan_id, tenant_id, status=status, limit=limit, offset=offset)

    async def get_architecture_profile(self, scan_id: UUID, tenant_id: UUID):
        run = await self.repository.get_scan_run(scan_id, tenant_id)
        if not run:
            return None
        return await self._ensure_architecture_profile(run, tenant_id)

    async def get_patch_safety_summary(self, scan_id: UUID, tenant_id: UUID) -> dict:
        run = await self.repository.get_scan_run(scan_id, tenant_id)
        if not run:
            raise ValueError("Repository scan not found")
        profile = await self._ensure_architecture_profile(run, tenant_id)
        return self.architecture_detector.patch_safety_summary(profile)

    async def _ensure_architecture_profile(self, run: RepoScanRun, tenant_id: UUID):
        existing = await self.repository.get_architecture_profile(run.id, tenant_id)
        if existing:
            return existing
        connection = await self.repository.get_connection(run.repo_connection_id, tenant_id)
        if not connection or not connection.local_path:
            raise ValueError("Repository connection local path not found")
        root = resolve_repo_root(connection.local_path)
        data = self.architecture_detector.detect(root)
        profile = await self.repository.create_architecture_profile(run, data.as_record())
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    def _merge_scanned_files(self, primary, additional):
        merged = []
        seen = set()
        for file in list(primary) + list(additional):
            if file.file_path in seen:
                continue
            seen.add(file.file_path)
            merged.append(file)
        return merged

    def _architecture_scanned_files(self, root: Path, profile: ArchitectureProfileData):
        scanned = []
        for file_path in self.architecture_detector.architecture_file_paths(profile):
            try:
                path = safe_child_path(root, file_path)
            except PathSafetyError:
                continue
            if not path.exists() or not path.is_file() or self.scanner._ignored(path, root):
                continue
            try:
                if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                    continue
            except OSError:
                continue
            scanned.append(self.scanner._scan_file(path, root))
        return scanned

    def _architecture_issue_candidates(
        self,
        profile: ArchitectureProfileData,
        scanned_by_path: Dict[str, object],
        file_by_path: Dict[str, object],
    ) -> List[RepoIssueCandidate]:
        candidates: List[RepoIssueCandidate] = []
        data = profile.as_record()
        for zone in data.get("manual_review_zones") or []:
            file_path = zone.get("file_path") or None
            if not file_path:
                continue
            scanned = scanned_by_path.get(file_path)
            candidates.append(
                RepoIssueCandidate(
                    file_path=file_path if file_path in file_by_path else None,
                    file_content_hash=getattr(scanned, "content_hash", "0" * 64),
                    issue_type=self._architecture_issue_type(zone),
                    severity=SeoCodeIssueSeverity.medium,
                    title=f"Manual review required: {zone.get('zone_type', 'repo architecture')}",
                    description=zone.get("reason") or "Architecture detection marked this area as manual-review only.",
                    recommended_fix="Review this repo architecture area manually before creating SEO code patches.",
                    source_reference_type=SeoCodeIssueSource.repo_scan,
                )
            )
        if data.get("detected_stack") in {"plain_static", "react_vite"}:
            for zone in data.get("safe_patch_zones") or []:
                file_path = zone.get("file_path")
                scanned = scanned_by_path.get(file_path or "")
                if not scanned or zone.get("zone_type") != "html_head":
                    continue
                content = getattr(scanned, "content", "")
                if not re.search(r"<title>.*?</title>", content, flags=re.I | re.S) or not re.search(
                    r"<meta\s+name=[\"']description[\"']",
                    content,
                    flags=re.I,
                ):
                    candidates.append(
                        RepoIssueCandidate(
                            file_path=file_path,
                            file_content_hash=getattr(scanned, "content_hash", "0" * 64),
                            issue_type=SeoCodeIssueType.weak_metadata,
                            severity=SeoCodeIssueSeverity.medium,
                            title="Weak HTML metadata",
                            description=f"{file_path} is missing a complete title or meta description in the HTML head.",
                            recommended_fix="Update title, meta description, and canonical tags in the HTML head only.",
                            source_reference_type=SeoCodeIssueSource.repo_scan,
                        )
                    )
        return candidates

    def _architecture_issue_type(self, zone: dict) -> SeoCodeIssueType:
        zone_type = str(zone.get("zone_type") or "")
        if "schema" in zone_type:
            return SeoCodeIssueType.missing_schema
        if "sitemap" in zone_type:
            return SeoCodeIssueType.route_not_in_sitemap
        if "robots" in zone_type:
            return SeoCodeIssueType.missing_robots
        if "metadata" in zone_type or "template" in zone_type:
            return SeoCodeIssueType.weak_metadata
        return SeoCodeIssueType.heading_semantics_risk

    async def generate_patches(self, scan_id: UUID, tenant_id: UUID) -> List[SeoCodePatch]:
        run = await self.repository.get_scan_run(scan_id, tenant_id)
        if not run:
            raise ValueError("Repository scan not found")
        connection = await self.repository.get_connection(run.repo_connection_id, tenant_id)
        if not connection or not connection.local_path:
            raise ValueError("Repository connection local path not found")
        root = resolve_repo_root(connection.local_path)
        architecture_profile = await self._ensure_architecture_profile(run, tenant_id)
        files = await self.repository.list_files(scan_id, tenant_id, limit=1000)
        file_by_id = {file.id: file for file in files}
        scanned_for_routes = self.scanner.discover_files(root)
        static_routes = static_routes_from_pages(scanned_for_routes)
        issues = await self.repository.list_issues(scan_id, tenant_id, status=SeoCodeIssueStatus.open, limit=1000)
        site_url = await self._site_url(run.project_id, run.tenant_id, fallback=connection.repo_url)
        records = []
        for issue in issues:
            patch_values = await self._patch_for_issue(issue, root, file_by_id, static_routes, site_url, architecture_profile)
            if not patch_values:
                continue
            existing = await self.repository.existing_patch(
                issue.id,
                patch_values["file_path"],
                patch_values["patch_type"],
                patch_values["original_content_hash"],
            )
            if not existing:
                records.append(patch_values)
        patches = await self.repository.add_patches(records)
        await self.repository.update_scan_patch_count(run, run.patches_created + len(patches))
        await self.db.commit()
        for patch in patches:
            await self.db.refresh(patch)
        if patches:
            from app.services.copy_review import SeoCopyReviewService

            copy_review = SeoCopyReviewService(self.db)
            for patch in patches:
                if patch.patch_type in {SeoCodePatchType.metadata_update, SeoCodePatchType.og_twitter_addition}:
                    try:
                        await copy_review.review_repo_patch(patch.id, tenant_id, apply_revision=True)
                    except Exception as exc:
                        logger.warning(
                            "Repo patch copy review failed",
                            patch_id=str(patch.id),
                            error=str(exc),
                        )
            for patch in patches:
                await self.db.refresh(patch)
        return patches

    async def list_patches(
        self,
        scan_id: UUID,
        tenant_id: UUID,
        status: Optional[SeoCodePatchStatus] = None,
        limit: int = 500,
        offset: int = 0,
    ):
        return await self.repository.list_patches(scan_id, tenant_id, status=status, limit=limit, offset=offset)

    async def get_patch(self, patch_id: UUID, tenant_id: UUID) -> Optional[SeoCodePatch]:
        return await self.repository.get_patch(patch_id, tenant_id)

    async def update_patch_status(
        self,
        patch_id: UUID,
        tenant_id: UUID,
        status: SeoCodePatchStatus,
    ) -> SeoCodePatch:
        patch = await self.repository.get_patch(patch_id, tenant_id)
        if not patch:
            raise ValueError("SEO code patch not found")
        if patch.risk_level == SeoCodePatchRisk.high and status == SeoCodePatchStatus.applied:
            raise ValueError("High-risk patches cannot be marked applied automatically in this phase")
        patch = await self.repository.set_patch_status(patch, status)
        await self.db.commit()
        await self.db.refresh(patch)
        return patch

    async def apply_approved_patches(
        self,
        scan_id: UUID,
        tenant_id: UUID,
        *,
        allow_high_risk: bool = False,
        run_validation: bool = False,
        validation_commands: Optional[Sequence[str]] = None,
    ) -> PatchApplyRun:
        """Apply approved patch records to a local git branch with safety checks."""
        run = await self.repository.get_scan_run(scan_id, tenant_id)
        if not run:
            raise ValueError("Repository scan not found")
        connection = await self.repository.get_connection(run.repo_connection_id, tenant_id)
        if not connection or not connection.local_path:
            raise ValueError("Repository connection local path not found")
        root = resolve_repo_root(connection.local_path)
        patches = await self.repository.list_patches(scan_id, tenant_id, limit=1000)
        branch_name = self._branch_name(scan_id)
        apply_run = await self.repository.create_apply_run(run, branch_name, len(patches))
        await self.repository.set_apply_run_status(apply_run, PatchApplyRunStatus.running)
        await self.db.commit()

        result_records = []
        applied_paths: List[str] = []
        validation_status = PatchValidationStatus.not_run
        validation_output = None
        git_diff_summary = None
        error_message = None
        final_status = PatchApplyRunStatus.completed

        try:
            self.git_runner.ensure_repo(root)
            self.git_runner.checkout_branch(root, branch_name)
            for patch in patches:
                result = await self._apply_single_patch(
                    apply_run=apply_run,
                    patch=patch,
                    root=root,
                    allow_high_risk=allow_high_risk,
                )
                result_records.append(result)
                if result["status"] == PatchApplyResultStatus.applied:
                    applied_paths.append(patch.file_path)
                    await self.repository.set_patch_status(patch, SeoCodePatchStatus.applied)

            if applied_paths:
                commands = self._validation_commands(run_validation, validation_commands)
                if commands:
                    validation = self.validation_runner.run(root, commands)
                    validation_status = PatchValidationStatus.passed if validation.passed else PatchValidationStatus.failed
                    validation_output = validation.output
                self.git_runner.add(root, applied_paths)
                git_diff_summary = self._git_cached_diff_summary(root) or self.git_runner.diff_summary(root)
                commit = self.git_runner.commit(root, "SEO Agent: apply approved SEO fixes")
                if commit.returncode != 0:
                    final_status = PatchApplyRunStatus.failed
                    error_message = f"git commit failed: {commit.output}"
            else:
                git_diff_summary = "No approved patches were applied."

            await self.repository.add_apply_results(result_records)
            patches_applied = len([record for record in result_records if record["status"] == PatchApplyResultStatus.applied])
            patches_failed = len(result_records) - patches_applied
            apply_run = await self.repository.finish_apply_run(
                apply_run,
                status=final_status,
                patches_applied=patches_applied,
                patches_failed=patches_failed,
                validation_status=validation_status,
                validation_output=validation_output,
                git_diff_summary=git_diff_summary,
                error_message=error_message,
            )
            await self.db.commit()
            await self.db.refresh(apply_run)
            logger.info(
                "Completed approved patch apply run",
                apply_run_id=str(apply_run.id),
                patches_applied=patches_applied,
                validation_status=validation_status.value,
            )
            return apply_run
        except Exception as exc:
            await self.repository.add_apply_results(result_records)
            apply_run = await self.repository.finish_apply_run(
                apply_run,
                status=PatchApplyRunStatus.failed,
                patches_applied=len([record for record in result_records if record["status"] == PatchApplyResultStatus.applied]),
                patches_failed=max(len(patches) - len(applied_paths), 0),
                validation_status=validation_status,
                validation_output=validation_output,
                git_diff_summary=git_diff_summary,
                error_message=str(exc),
            )
            await self.db.commit()
            logger.error("Approved patch apply run failed", apply_run_id=str(apply_run.id), error=str(exc), exc_info=True)
            if isinstance(exc, PathSafetyError):
                raise
            if isinstance(exc, GitCommandError):
                raise RepoAgentError(str(exc)) from exc
            if isinstance(exc, RepoAgentError):
                raise
            raise RepoAgentError(str(exc)) from exc

    async def get_apply_run_status(self, apply_run_id: UUID, tenant_id: UUID) -> Optional[PatchApplyRun]:
        return await self.repository.get_apply_run(apply_run_id, tenant_id)

    async def list_apply_results(self, apply_run_id: UUID, tenant_id: UUID, limit: int = 500, offset: int = 0):
        apply_run = await self.repository.get_apply_run(apply_run_id, tenant_id)
        if not apply_run:
            raise ValueError("Patch apply run not found")
        return await self.repository.list_apply_results(apply_run_id, tenant_id, limit=limit, offset=offset)

    async def create_pull_request(
        self,
        apply_run_id: UUID,
        tenant_id: UUID,
        *,
        force_pr_on_validation_failure: bool = False,
        draft: bool = True,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> PullRequestRecord:
        apply_run = await self.repository.get_apply_run(apply_run_id, tenant_id)
        if not apply_run:
            raise ValueError("Patch apply run not found")
        connection = await self.repository.get_connection(apply_run.repo_connection_id, tenant_id)
        if not connection:
            raise ValueError("Repository connection not found")
        base_branch = connection.default_branch or settings.GITHUB_DEFAULT_BASE_BRANCH
        pr_title = title or "SEO Agent: approved SEO fixes"
        body = description or await self._build_pr_body(apply_run, tenant_id)

        missing = []
        if not settings.GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if not connection.repo_url:
            missing.append("repo_url")
        if not base_branch:
            missing.append("default_branch")
        if not apply_run.branch_name:
            missing.append("branch_name")
        if self._enum_value(apply_run.validation_status) == PatchValidationStatus.failed.value and not force_pr_on_validation_failure:
            missing.append("force_pr_on_validation_failure")
        if apply_run.patches_applied <= 0:
            missing.append("applied_patches")
        if self._enum_value(apply_run.status) == PatchApplyRunStatus.rolled_back.value:
            missing.append("not_rolled_back")

        if missing:
            record = await self.repository.create_pull_request_record(
                tenant_id=apply_run.tenant_id,
                project_id=apply_run.project_id,
                repo_connection_id=apply_run.repo_connection_id,
                apply_run_id=apply_run.id,
                branch_name=apply_run.branch_name or "",
                base_branch=base_branch or "",
                title=pr_title,
                description=body,
                status=PullRequestStatus.failed,
                error_message=f"Skipped PR creation; missing or blocked by: {', '.join(missing)}",
            )
            await self.db.commit()
            await self.db.refresh(record)
            return record

        root = resolve_repo_root(connection.local_path or "")
        commit_sha = self.git_runner.commit_sha(root)
        push = self.git_runner.push_branch(root, apply_run.branch_name)
        if push.returncode != 0:
            record = await self.repository.create_pull_request_record(
                tenant_id=apply_run.tenant_id,
                project_id=apply_run.project_id,
                repo_connection_id=apply_run.repo_connection_id,
                apply_run_id=apply_run.id,
                branch_name=apply_run.branch_name,
                base_branch=base_branch,
                title=pr_title,
                description=body,
                status=PullRequestStatus.failed,
                commit_sha=commit_sha,
                error_message=f"git push failed: {push.output}",
            )
            await self.db.commit()
            await self.db.refresh(record)
            return record

        try:
            created = await self.github_client.create_draft_pr(
                repo_url=connection.repo_url,
                token=settings.GITHUB_TOKEN,
                branch_name=apply_run.branch_name,
                base_branch=base_branch,
                title=pr_title,
                body=body,
                draft=draft,
            )
            record = await self.repository.create_pull_request_record(
                tenant_id=apply_run.tenant_id,
                project_id=apply_run.project_id,
                repo_connection_id=apply_run.repo_connection_id,
                apply_run_id=apply_run.id,
                branch_name=apply_run.branch_name,
                base_branch=base_branch,
                title=pr_title,
                description=body,
                status=PullRequestStatus.draft if draft else PullRequestStatus.open,
                commit_sha=commit_sha,
                pr_number=created.number,
                pr_url=created.url,
            )
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except GitHubClientError as exc:
            record = await self.repository.create_pull_request_record(
                tenant_id=apply_run.tenant_id,
                project_id=apply_run.project_id,
                repo_connection_id=apply_run.repo_connection_id,
                apply_run_id=apply_run.id,
                branch_name=apply_run.branch_name,
                base_branch=base_branch,
                title=pr_title,
                description=body,
                status=PullRequestStatus.failed,
                commit_sha=commit_sha,
                error_message=str(exc),
            )
            await self.db.commit()
            await self.db.refresh(record)
            return record

    async def get_pull_request(self, pr_id: UUID, tenant_id: UUID) -> Optional[PullRequestRecord]:
        return await self.repository.get_pull_request(pr_id, tenant_id)

    async def rollback_apply_run(self, apply_run_id: UUID, tenant_id: UUID) -> PatchApplyRun:
        apply_run = await self.repository.get_apply_run(apply_run_id, tenant_id)
        if not apply_run:
            raise ValueError("Patch apply run not found")
        connection = await self.repository.get_connection(apply_run.repo_connection_id, tenant_id)
        if not connection or not connection.local_path:
            raise ValueError("Repository connection local path not found")
        root = resolve_repo_root(connection.local_path)
        results = await self.repository.list_apply_results(apply_run.id, tenant_id, limit=1000)
        restored_paths: List[str] = []
        self.git_runner.run(root, ["checkout", apply_run.branch_name])
        for result in results:
            if self._enum_value(result.status) != PatchApplyResultStatus.applied.value:
                continue
            backup_path = Path(result.backup_path or "")
            if not backup_path.exists() or not backup_path.is_file():
                await self.repository.set_apply_result_status(
                    result,
                    PatchApplyResultStatus.failed,
                    "Rollback backup file is missing.",
                )
                continue
            target = safe_child_path(root, result.file_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(read_repo_text(backup_path), encoding="utf-8")
            await self.repository.set_apply_result_status(result, PatchApplyResultStatus.rolled_back, "Restored from backup.")
            patch = await self.repository.get_patch(result.patch_id, tenant_id)
            if patch:
                await self.repository.set_patch_status(patch, SeoCodePatchStatus.approved)
            restored_paths.append(result.file_path)

        if restored_paths:
            self.git_runner.add(root, restored_paths)
            self.git_runner.commit(root, "SEO Agent: rollback approved SEO fixes")
        apply_run = await self.repository.finish_apply_run(
            apply_run,
            status=PatchApplyRunStatus.rolled_back,
            patches_applied=apply_run.patches_applied,
            patches_failed=apply_run.patches_failed,
            validation_status=apply_run.validation_status,
            validation_output=apply_run.validation_output,
            git_diff_summary=apply_run.git_diff_summary,
            error_message=None,
        )
        await self.db.commit()
        await self.db.refresh(apply_run)
        return apply_run

    async def _apply_single_patch(
        self,
        *,
        apply_run: PatchApplyRun,
        patch: SeoCodePatch,
        root: Path,
        allow_high_risk: bool,
    ) -> dict:
        base = {
            "tenant_id": apply_run.tenant_id,
            "project_id": apply_run.project_id,
            "apply_run_id": apply_run.id,
            "patch_id": patch.id,
            "file_path": patch.file_path,
            "original_content_hash": patch.original_content_hash,
        }
        if self._enum_value(patch.status) != SeoCodePatchStatus.approved.value:
            return {**base, "status": PatchApplyResultStatus.skipped, "reason": "Patch is not approved."}
        if self._enum_value(patch.risk_level) == SeoCodePatchRisk.high.value and not allow_high_risk:
            return {
                **base,
                "status": PatchApplyResultStatus.skipped,
                "reason": "High-risk patch requires allow_high_risk=true.",
            }
        if self._is_ignored_patch_path(patch.file_path):
            return {**base, "status": PatchApplyResultStatus.skipped, "reason": "Patch targets an ignored folder."}
        try:
            target = safe_child_path(root, patch.file_path)
        except PathSafetyError as exc:
            return {**base, "status": PatchApplyResultStatus.failed, "reason": str(exc)}
        current_content = read_repo_text(target) if target.exists() else ""
        current_hash = content_hash(current_content)
        if current_hash != patch.original_content_hash:
            return {
                **base,
                "status": PatchApplyResultStatus.skipped,
                "reason": "Hash mismatch conflict; current file content differs from the proposed patch base.",
                "new_content_hash": current_hash,
            }
        backup = self._write_backup(root, apply_run.id, patch.id, patch.file_path, current_content)
        target.parent.mkdir(parents=True, exist_ok=True)
        proposed = patch.proposed_content or ""
        target.write_text(proposed, encoding="utf-8")
        return {
            **base,
            "status": PatchApplyResultStatus.applied,
            "reason": "Patch applied to working branch.",
            "new_content_hash": content_hash(proposed),
            "backup_path": str(backup),
        }

    def _branch_name(self, scan_id: UUID) -> str:
        return f"seo-agent/{str(scan_id)[:8]}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    def _validation_commands(
        self,
        run_validation: bool,
        validation_commands: Optional[Sequence[str]],
    ) -> List[str]:
        if not run_validation:
            return []
        if validation_commands:
            return [command.strip() for command in validation_commands if command.strip()]
        return self.validation_runner.parse_commands(settings.REPO_AGENT_VALIDATION_COMMANDS)

    def _git_cached_diff_summary(self, root: Path) -> str:
        result = self.git_runner.run(root, ["diff", "--cached", "--stat"])
        return result.output if result.returncode == 0 else result.output

    def _write_backup(self, root: Path, apply_run_id: UUID, patch_id: UUID, file_path: str, content: str) -> Path:
        safe_name = file_path.replace("\\", "/").replace("/", "__")
        backup_dir = root.parent / ".seo-agent-backups" / root.name / str(apply_run_id)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{patch_id}-{safe_name}"
        backup_path.write_text(content, encoding="utf-8")
        return backup_path

    def _is_ignored_patch_path(self, file_path: str) -> bool:
        parts = [part for part in file_path.replace("\\", "/").split("/") if part]
        return any(part in IGNORE_DIRS for part in parts)

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)

    async def _build_pr_body(self, apply_run: PatchApplyRun, tenant_id: UUID) -> str:
        results = await self.repository.list_apply_results(apply_run.id, tenant_id, limit=1000)
        applied = [result for result in results if self._enum_value(result.status) == PatchApplyResultStatus.applied.value]
        files = sorted({result.file_path for result in applied})
        issue_ids = []
        for result in applied:
            patch = await self.repository.get_patch(result.patch_id, tenant_id)
            if patch:
                issue_ids.append(str(patch.issue_id))
        validation = apply_run.validation_status.value
        if apply_run.validation_output:
            validation = f"{validation}\n\n```\n{apply_run.validation_output[:4000]}\n```"
        return (
            "## SEO Agent approved fixes\n\n"
            f"- Applied patches: {len(applied)}\n"
            f"- Files changed: {', '.join(files) if files else 'none'}\n"
            f"- Issues fixed: {', '.join(sorted(set(issue_ids))) if issue_ids else 'not available'}\n"
            f"- Validation result: {validation}\n\n"
            "Review these SEO-only changes before merge. This PR was created as a controlled draft and was not auto-merged or deployed."
        )

    async def _signal_issue_candidates(
        self,
        run: RepoScanRun,
        scanned_files,
        file_by_path: Dict[str, object],
    ) -> List[RepoIssueCandidate]:
        candidates: List[RepoIssueCandidate] = []
        content_suggestions = await self.repository.list_content_suggestions(run.tenant_id, run.project_id)
        search_opportunities = await self.repository.list_search_console_opportunities(run.tenant_id, run.project_id)
        geo_recs = await self.repository.list_geo_aeo_recommendations(run.tenant_id, run.project_id)
        default_file = self._default_page_file(scanned_files)

        for suggestion in content_suggestions:
            file_path = self._file_for_url(getattr(suggestion, "evidence", {}) or {}, scanned_files) or default_file
            if suggestion.suggestion_type in {
                ContentOptimizationSuggestionType.seo_title,
                ContentOptimizationSuggestionType.meta_description,
            }:
                candidates.append(
                    self._source_candidate(
                        file_path,
                        file_by_path,
                        SeoCodeIssueType.weak_metadata,
                        SeoCodeIssueSeverity.medium,
                        "Content optimization metadata signal",
                        "A stored content optimization suggestion recommends improving SEO title or meta description.",
                        "Generate a metadata-only patch that preserves visible UI.",
                        SeoCodeIssueSource.content_optimization,
                        suggestion.id,
                    )
                )
            elif suggestion.suggestion_type in {ContentOptimizationSuggestionType.schema, ContentOptimizationSuggestionType.faq}:
                candidates.append(
                    self._source_candidate(
                        file_path,
                        file_by_path,
                        SeoCodeIssueType.missing_schema,
                        SeoCodeIssueSeverity.medium,
                        "Content optimization schema signal",
                        "A stored content optimization suggestion recommends schema or FAQ structured data.",
                        "Generate a JSON-LD patch where a safe page component is available.",
                        SeoCodeIssueSource.content_optimization,
                        suggestion.id,
                    )
                )
        for opportunity in search_opportunities:
            if opportunity.opportunity_type not in {
                SearchConsoleOpportunityType.high_impressions_low_ctr,
                SearchConsoleOpportunityType.ctr_drop,
                SearchConsoleOpportunityType.metadata_rewrite,
            }:
                continue
            file_path = self._path_for_page_url(opportunity.page_url, scanned_files) or default_file
            candidates.append(
                self._source_candidate(
                    file_path,
                    file_by_path,
                    SeoCodeIssueType.weak_metadata,
                    SeoCodeIssueSeverity.high,
                    "Search Console metadata opportunity",
                    f"Search Console query '{opportunity.query}' indicates the page may need title/meta refinement.",
                    "Generate a metadata-only patch for human review.",
                    SeoCodeIssueSource.search_console,
                    opportunity.id,
                )
            )
        for rec in geo_recs:
            rec_type = str(getattr(rec, "recommendation_type", ""))
            if "schema" not in rec_type and "answer" not in rec_type and "faq" not in rec_type:
                continue
            candidates.append(
                self._source_candidate(
                    default_file,
                    file_by_path,
                    SeoCodeIssueType.missing_schema,
                    SeoCodeIssueSeverity.medium,
                    "GEO/AEO structured data signal",
                    "A GEO/AEO recommendation suggests improving answer/schema readiness.",
                    "Generate a JSON-LD patch for review if the page can safely accept hidden structured data.",
                    SeoCodeIssueSource.geo_aeo,
                    rec.id,
                )
            )
        return [candidate for candidate in candidates if candidate.file_path]

    def _issue_record(
        self,
        run: RepoScanRun,
        candidate: RepoIssueCandidate,
        file_by_path: Dict[str, object],
    ) -> dict:
        file = file_by_path.get(candidate.file_path or "")
        return {
            "tenant_id": run.tenant_id,
            "project_id": run.project_id,
            "repo_connection_id": run.repo_connection_id,
            "scan_run_id": run.id,
            "file_id": getattr(file, "id", None),
            "issue_type": candidate.issue_type,
            "severity": candidate.severity,
            "title": candidate.title[:255],
            "description": candidate.description,
            "recommended_fix": candidate.recommended_fix,
            "source_reference_type": candidate.source_reference_type,
            "source_reference_id": candidate.source_reference_id,
            "status": SeoCodeIssueStatus.open,
        }

    def _source_candidate(
        self,
        file_path: Optional[str],
        file_by_path: Dict[str, object],
        issue_type: SeoCodeIssueType,
        severity: SeoCodeIssueSeverity,
        title: str,
        description: str,
        recommended_fix: str,
        source_type: SeoCodeIssueSource,
        source_id: UUID,
    ) -> RepoIssueCandidate:
        file = file_by_path.get(file_path or "")
        return RepoIssueCandidate(
            file_path=file_path,
            file_content_hash=getattr(file, "content_hash", "0" * 64),
            issue_type=issue_type,
            severity=severity,
            title=title,
            description=description,
            recommended_fix=recommended_fix,
            source_reference_type=source_type,
            source_reference_id=source_id,
        )

    async def _patch_for_issue(
        self,
        issue: SeoCodeIssue,
        root: Path,
        file_by_id: Dict[UUID, object],
        static_routes: List[str],
        site_url: str,
        architecture_profile,
    ) -> Optional[dict]:
        target_file = file_by_id.get(issue.file_id) if issue.file_id else None
        file_path = getattr(target_file, "file_path", None)
        patch_type = None
        proposed = None
        original = ""
        original_hash = "0" * 64
        risk = SeoCodePatchRisk.low

        if issue.issue_type in {
            SeoCodeIssueType.missing_metadata,
            SeoCodeIssueType.weak_metadata,
            SeoCodeIssueType.missing_canonical,
            SeoCodeIssueType.missing_open_graph,
            SeoCodeIssueType.missing_twitter_meta,
        } and file_path:
            file_path = self._metadata_patch_target_file(root, file_path)
            if not file_path:
                return None
            path = safe_child_path(root, file_path)
            original = read_repo_text(path)
            original_hash = content_hash(original)
            route_label = label_from_route(file_path, fallback="Website Page")
            canonical = self._canonical_for_file(file_path, site_url)
            if file_path.endswith(".html"):
                proposed = html_metadata_patch_content(original, route_label, canonical)
            else:
                proposed = metadata_patch_content(original, route_label, canonical)
            patch_type = (
                SeoCodePatchType.metadata_update
                if issue.issue_type in {SeoCodeIssueType.missing_metadata, SeoCodeIssueType.weak_metadata}
                else SeoCodePatchType.og_twitter_addition
            )
        elif issue.issue_type == SeoCodeIssueType.missing_schema and file_path:
            if self._is_internal_patch_path(file_path):
                return None
            path = safe_child_path(root, file_path)
            original = read_repo_text(path)
            if is_client_component(original):
                return None
            original_hash = content_hash(original)
            route_label = label_from_route(file_path, fallback="Website Page")
            proposed = schema_patch_content(original, route_label, self._canonical_for_file(file_path, site_url))
            patch_type = SeoCodePatchType.schema_addition
            risk = SeoCodePatchRisk.medium
        elif issue.issue_type == SeoCodeIssueType.missing_robots:
            file_path = "app/robots.ts"
            path = safe_child_path(root, file_path)
            if path.exists():
                return None
            original = ""
            original_hash = content_hash(original)
            proposed = robots_patch_content(site_url)
            patch_type = SeoCodePatchType.robots_update
        elif issue.issue_type in {SeoCodeIssueType.missing_sitemap, SeoCodeIssueType.route_not_in_sitemap}:
            file_path = "app/sitemap.ts"
            path = safe_child_path(root, file_path)
            original = read_repo_text(path) if path.exists() else ""
            original_hash = content_hash(original)
            proposed = sitemap_patch_content(static_routes or ["/"], site_url, original=original)
            patch_type = SeoCodePatchType.sitemap_update
        elif issue.issue_type in {SeoCodeIssueType.heading_semantics_risk, SeoCodeIssueType.missing_alt_pattern}:
            return None

        if not patch_type or proposed is None or proposed == original:
            return None
        safety = self.architecture_detector.classify_patch(
            architecture_profile,
            file_path=file_path,
            patch_type=patch_type,
            issue_type=issue.issue_type,
            original_content=original,
        )
        if not safety.is_safe:
            logger.info(
                "Skipped repo patch by safety classifier",
                scan_id=str(issue.scan_run_id),
                file_path=file_path,
                patch_type=patch_type.value,
                classification=safety.classification,
                reason=safety.reason,
            )
            return None
        diff = build_unified_diff(file_path, original, proposed)
        return {
            "tenant_id": issue.tenant_id,
            "project_id": issue.project_id,
            "repo_connection_id": issue.repo_connection_id,
            "scan_run_id": issue.scan_run_id,
            "issue_id": issue.id,
            "file_path": file_path,
            "patch_type": patch_type,
            "original_content_hash": original_hash,
            "diff_text": diff,
            "proposed_content": proposed,
            "explanation": self._patch_explanation(issue, patch_type, safety.reason),
            "risk_level": risk,
            "status": SeoCodePatchStatus.proposed,
        }

    def _patch_explanation(self, issue: SeoCodeIssue, patch_type: SeoCodePatchType, safety_reason: Optional[str] = None) -> str:
        safety = f" Safety reason: {safety_reason}" if safety_reason else ""
        return (
            f"Proposes a {patch_type.value} patch for {issue.issue_type.value}. "
            "The patch is review-only and avoids Tailwind class, visible layout, commit, push, deploy, or publishing changes."
            f"{safety}"
        )

    def _metadata_patch_target_file(self, root: Path, file_path: str) -> Optional[str]:
        if self._is_internal_patch_path(file_path):
            return None
        path = safe_child_path(root, file_path)
        original = read_repo_text(path) if path.exists() else ""
        if not is_client_component(original):
            return file_path
        if file_path.endswith("/page.tsx"):
            layout_path = file_path.removesuffix("/page.tsx") + "/layout.tsx"
            layout = safe_child_path(root, layout_path)
            if layout.exists():
                return layout_path
        return None

    def _is_internal_patch_path(self, file_path: str) -> bool:
        clean = file_path.replace("\\", "/").removeprefix("app/").strip("/")
        first = clean.split("/", 1)[0]
        return first in {"admin", "api", "_components", "dashboard"}

    async def _site_url(self, project_id: Optional[UUID], tenant_id: UUID, fallback: Optional[str] = None) -> str:
        if project_id:
            project = await self.repository.get_project(project_id, tenant_id)
            if project and project.domain:
                domain = project.domain.strip()
                if domain.startswith("http://") or domain.startswith("https://"):
                    return domain.rstrip("/")
                return f"https://{domain.strip('/')}"
        if fallback and fallback.startswith("http"):
            return fallback.rstrip("/")
        return "https://example.com"

    def _canonical_for_file(self, file_path: str, site_url: str) -> str:
        if file_path.endswith(".html"):
            route = file_path.removeprefix("public/").removesuffix(".html")
            route = route.removesuffix("/index")
            if route == "index":
                route = ""
            route = "/" + route.strip("/") if route else "/"
            return site_url.rstrip("/") + ("" if route == "/" else route)
        route = file_path.removeprefix("app/").removesuffix("/page.tsx").removesuffix("page.tsx")
        route = "/" + route.strip("/")
        if file_path.endswith("layout.tsx") or route == "/":
            route = "/"
        return site_url.rstrip("/") + ("" if route == "/" else route)

    def _default_page_file(self, scanned_files) -> Optional[str]:
        for preferred in ["app/page.tsx", "app/layout.tsx"]:
            if any(file.file_path == preferred for file in scanned_files):
                return preferred
        for file in scanned_files:
            if file.detected_purpose in {RepoFilePurpose.page, RepoFilePurpose.layout}:
                return file.file_path
        return None

    def _file_for_url(self, evidence: dict, scanned_files) -> Optional[str]:
        url = evidence.get("url") if isinstance(evidence, dict) else None
        return self._path_for_page_url(url, scanned_files) if url else None

    def _path_for_page_url(self, page_url: Optional[str], scanned_files) -> Optional[str]:
        if not page_url:
            return None
        path = urlsplit(page_url).path.strip("/")
        expected = "app/page.tsx" if not path else f"app/{path}/page.tsx"
        if any(file.file_path == expected for file in scanned_files):
            return expected
        tokens = set(re.findall(r"[a-z0-9]+", path.lower()))
        best = None
        best_score = 0
        for file in scanned_files:
            if file.detected_purpose != RepoFilePurpose.page:
                continue
            file_tokens = set(re.findall(r"[a-z0-9]+", file.file_path.lower()))
            score = len(tokens.intersection(file_tokens))
            if score > best_score:
                best = file.file_path
                best_score = score
        return best
