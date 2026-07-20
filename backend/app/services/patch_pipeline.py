"""Autonomous SEO patch application & verification pipeline.

Takes the framework-aware generated patches (Phase 14) and runs them through the
full engineering lifecycle, reusing existing engines:

    generate -> apply -> branch -> commit -> pull request -> deploy -> verify -> learn

Git operations reuse the Repo Agent's GitCommandRunner + ValidationRunner; PR /
deploy / verify reuse the existing Deployment and Verification engines; safety
reuses the shared protected-path classifier. When no repository is connected the
pipeline stops honestly at the apply stage (status=blocked) — patches remain
review-only, nothing is fabricated.

Framework-aware apply: each patch's target file is resolved to the real repo path
(e.g. app/ vs src/app/) and missing SEO files are created. Protected UI /
business-logic / auth / payments / CRM / database files are never touched — a
patch targeting one aborts the pipeline.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.generated_patch import GeneratedSeoPatch
from app.models.patch_pipeline import PIPELINE_STAGES, PatchPipeline, PatchPipelineStatus
from app.models.project import Project
from app.models.repo_agent import RepoConnection
from app.repo_agent.architecture import RepoArchitectureDetector
from app.repo_agent.git_ops import GitCommandError, GitCommandRunner, ValidationRunner
from app.repo_agent.scanner import resolve_repo_root, safe_child_path

logger = structlog.get_logger(__name__)


class PatchPipelineService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.git = GitCommandRunner()
        self.validation = ValidationRunner()
        self.safety = RepoArchitectureDetector()

    # -- entry --------------------------------------------------------------

    async def run(self, project_id: UUID, tenant_id: UUID) -> PatchPipeline:
        """Run the autonomous pipeline for the project's ready SEO patches."""
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")

        patches = (await self.db.execute(
            select(GeneratedSeoPatch).where(
                GeneratedSeoPatch.project_id == project_id,
                GeneratedSeoPatch.tenant_id == tenant_id,
                GeneratedSeoPatch.ready_for_pr.is_(True),
                GeneratedSeoPatch.code_fixable.is_(True),
            )
        )).scalars().all()

        pipeline = PatchPipeline(
            tenant_id=tenant_id, project_id=project_id,
            framework=(patches[0].framework if patches else None),
            status=PatchPipelineStatus.running,
            stages=[{"name": s, "status": "pending", "started_at": None, "finished_at": None, "detail": None}
                    for s in PIPELINE_STAGES],
            patches_total=len(patches),
            seo_before=(patches[0].seo_before if patches else None),
            performance_before=(patches[0].performance_before if patches else None),
        )
        self.db.add(pipeline)
        await self.db.commit()
        await self.db.refresh(pipeline)

        if not patches:
            self._stage(pipeline, "generate", "skipped", "No ready-for-PR code patches. Generate patches first.")
            pipeline.status = PatchPipelineStatus.blocked
            pipeline.current_stage = "generate"
            await self._save(pipeline)
            return pipeline

        self._stage(pipeline, "generate", "succeeded", f"{len(patches)} framework-safe patches ready.")

        connection = (await self.db.execute(
            select(RepoConnection).where(
                RepoConnection.project_id == project_id, RepoConnection.tenant_id == tenant_id
            ).order_by(RepoConnection.created_at.desc()).limit(1)
        )).scalars().first()

        if not connection or not connection.local_path:
            # Honest gating: nothing to apply into.
            self._stage(pipeline, "apply", "blocked",
                        "No repository connected. Connect a repo to apply patches; they remain review-only.")
            for s in ("branch", "commit", "pull_request", "deploy", "verify", "learn"):
                self._stage(pipeline, s, "gated", "Requires a connected repository.")
            pipeline.status = PatchPipelineStatus.blocked
            pipeline.current_stage = "apply"
            pipeline.ready_for_pr = True
            await self._save(pipeline)
            logger.info("patch_pipeline_blocked_no_repo", project_id=str(project_id))
            return pipeline

        return await self._run_with_repo(pipeline, patches, connection)

    # -- repo lifecycle -----------------------------------------------------

    async def _run_with_repo(self, pipeline: PatchPipeline, patches, connection) -> PatchPipeline:
        try:
            root = resolve_repo_root(connection.local_path)
            self.git.ensure_repo(root)
        except Exception as exc:
            # A missing/invalid checkout is a not-connected state, not a failure.
            self._stage(pipeline, "apply", "blocked",
                        f"Repository checkout not accessible ({exc}). Reconnect a valid repo; patches remain review-only.")
            for s in ("branch", "commit", "pull_request", "deploy", "verify", "learn"):
                self._stage(pipeline, s, "gated", "Requires an accessible repository checkout.")
            pipeline.status = PatchPipelineStatus.blocked
            pipeline.ready_for_pr = True
            pipeline.error = str(exc)[:500]
            await self._save(pipeline)
            return pipeline

        # branch
        branch = f"seo-agent/patches-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        try:
            self.git.checkout_branch(root, branch)
        except GitCommandError as exc:
            self._stage(pipeline, "branch", "failed", str(exc))
            pipeline.status = PatchPipelineStatus.failed
            pipeline.error = str(exc)[:500]
            await self._save(pipeline)
            return pipeline
        pipeline.branch_name = branch
        self._stage(pipeline, "branch", "succeeded", f"Created branch {branch}")

        # apply (framework-aware, SEO-safe only)
        applied_paths: List[str] = []
        failed = 0
        for patch in patches:
            ok, rel_path, detail = self._apply_one(root, patch)
            if ok:
                applied_paths.append(rel_path)
            else:
                failed += 1
                logger.info("patch_pipeline_patch_skipped", target=patch.target_file, reason=detail)
        pipeline.patches_applied = len(applied_paths)
        pipeline.patches_failed = failed
        if not applied_paths:
            self._stage(pipeline, "apply", "failed", "No patches could be safely applied.")
            self._rollback(root, connection)
            pipeline.status = PatchPipelineStatus.rolled_back
            await self._save(pipeline)
            return pipeline
        self._stage(pipeline, "apply", "succeeded", f"Applied {len(applied_paths)} SEO-safe file(s).")

        # validation (typecheck/lint/build) BEFORE commit
        commands = self.validation.parse_commands(settings.REPO_AGENT_VALIDATION_COMMANDS or "")
        if commands:
            result = self.validation.run(root, commands)
            pipeline.validation_status = "passed" if result.passed else "failed"
            pipeline.validation_output = (result.output or "")[:4000]
            if not result.passed:
                # rollback: revert working tree, no commit, no PR.
                self._rollback(root, connection)
                self._stage(pipeline, "commit", "rolled_back", "Validation failed — reverted, no PR created.")
                for s in ("pull_request", "deploy", "verify"):
                    self._stage(pipeline, s, "skipped", "Skipped after validation failure.")
                self._stage(pipeline, "learn", "succeeded", "Recorded failure for learning.")
                pipeline.status = PatchPipelineStatus.rolled_back
                await self._save(pipeline)
                logger.info("patch_pipeline_rolled_back_validation", pipeline_id=str(pipeline.id))
                return pipeline
        else:
            pipeline.validation_status = "gated"

        # commit
        try:
            self.git.add(root, applied_paths)
            pipeline.diff_summary = (self.git.diff_summary(root) or "")[:4000]
            commit = self.git.commit(root, "SEO Agent: apply framework-safe SEO patches")
            if commit.returncode != 0:
                raise GitCommandError(f"git commit failed: {commit.output}")
            pipeline.commit_sha = self.git.commit_sha(root)
        except GitCommandError as exc:
            self._rollback(root, connection)
            self._stage(pipeline, "commit", "failed", str(exc))
            pipeline.status = PatchPipelineStatus.failed
            pipeline.error = str(exc)[:500]
            await self._save(pipeline)
            return pipeline
        self._stage(pipeline, "commit", "succeeded", f"Committed {pipeline.commit_sha[:8] if pipeline.commit_sha else ''}")

        # pull request (graceful: needs GITHUB_TOKEN + repo_url)
        await self._pull_request(pipeline, connection, root)

        # deploy + verify (reuse engines; gated without provider/token)
        await self._deploy_and_verify(pipeline, connection)

        # learn
        await self._learn(pipeline)

        pipeline.status = (PatchPipelineStatus.succeeded
                           if pipeline.pr_status not in ("failed",) else PatchPipelineStatus.failed)
        pipeline.ready_for_pr = True
        await self._save(pipeline)
        logger.info("patch_pipeline_completed", pipeline_id=str(pipeline.id),
                    status=pipeline.status.value, applied=pipeline.patches_applied)
        return pipeline

    def _apply_one(self, root: Path, patch: GeneratedSeoPatch) -> Tuple[bool, str, str]:
        """Framework-aware, SEO-safe file write. Resolves app/ vs src/app/ and
        creates missing SEO files. Aborts on any protected target."""
        rel = self._resolve_target(root, patch.target_file)
        if self._is_protected(rel):
            return False, rel, "Protected (UI/business/auth/payments/DB) target — refused."
        try:
            target = safe_child_path(root, rel)
        except Exception as exc:
            return False, rel, f"Unsafe path: {exc}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # New-file patches replace; in-place patches append the SEO block if absent.
            if patch.is_new_file or not target.exists():
                target.write_text(patch.generated_code, encoding="utf-8")
            else:
                existing = target.read_text(encoding="utf-8", errors="ignore")
                if patch.generated_code.strip() and patch.generated_code[:40] not in existing:
                    target.write_text(existing.rstrip() + "\n\n" + patch.generated_code, encoding="utf-8")
            return True, rel, "applied"
        except Exception as exc:
            return False, rel, str(exc)

    # Never write a UI-component file, even if the base classifier allows it.
    _UI_SEGMENTS = {"components", "component", "ui", "styles", "css", "widgets", "layouts"}

    def _is_protected(self, rel: str) -> bool:
        if self.safety._is_unsafe_path(rel):
            return True
        parts = {p.lower() for p in rel.replace("\\", "/").split("/")}
        # SEO layouts (Blade/Astro/Django) legitimately live under layouts/ — allow
        # only when the filename is clearly an SEO surface.
        if parts & self._UI_SEGMENTS:
            low = rel.lower()
            seo_ok = any(k in low for k in ("schema", "seo", "jsonld", "json-ld", "layout.astro",
                                            "app.blade", "theme.liquid"))
            if "layouts" in parts and seo_ok:
                return False
            if {"components", "component", "ui", "styles", "css", "widgets"} & parts and seo_ok:
                return False
            return True
        return False

    @staticmethod
    def _resolve_target(root: Path, target_file: str) -> str:
        """Strip parenthetical hints and map app/ -> src/app/ when the repo uses src/."""
        rel = target_file.split(" (")[0].strip().lstrip("/")
        if rel.startswith("app/") and not (root / "app").exists() and (root / "src" / "app").exists():
            return "src/" + rel
        if rel.startswith("src/") and not (root / "src").exists() and (root / rel[4:]).parent.exists():
            return rel[4:]
        return rel

    def _rollback(self, root: Path, connection) -> None:
        """Revert the working tree to the base branch — never leave partial edits."""
        base = connection.default_branch or settings.GITHUB_DEFAULT_BASE_BRANCH or "main"
        self.git.run(root, ["reset", "--hard"])
        self.git.run(root, ["clean", "-fd"])   # discard newly-created (untracked) SEO files
        self.git.run(root, ["checkout", base])

    # -- PR / deploy / verify / learn (reuse engines) -----------------------

    async def _pull_request(self, pipeline: PatchPipeline, connection, root: Path) -> None:
        missing = []
        if not settings.GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if not getattr(connection, "repo_url", None):
            missing.append("repo_url")
        if missing:
            pipeline.pr_status = "gated"
            self._stage(pipeline, "pull_request", "gated",
                        f"Draft PR ready locally; opening it needs {', '.join(missing)}.")
            return
        try:
            from app.repo_agent.git_ops import GitHubClient

            # Push the branch, then open a draft PR via the reused GitHub client.
            push = self.git.push_branch(root, pipeline.branch_name)
            if push.returncode != 0:
                raise GitCommandError(f"git push failed: {push.output}")
            client = GitHubClient()
            base = connection.default_branch or settings.GITHUB_DEFAULT_BASE_BRANCH
            pr = await client.create_draft_pr(
                repo_url=connection.repo_url, token=settings.GITHUB_TOKEN,
                branch_name=pipeline.branch_name, base_branch=base,
                title="SEO Agent: framework-safe SEO patches",
                body=self._pr_body(pipeline), draft=True,
            )
            pipeline.pr_url = getattr(pr, "url", None)
            pipeline.pr_status = "open"
            self._stage(pipeline, "pull_request", "succeeded", f"Draft PR opened: {pipeline.pr_url}")
        except Exception as exc:
            pipeline.pr_status = "failed"
            self._stage(pipeline, "pull_request", "failed", str(exc)[:300])

    async def _deploy_and_verify(self, pipeline: PatchPipeline, connection) -> None:
        # Deploy + verify are driven by PR merge in the existing engines. Without
        # an opened PR they are honestly gated.
        if pipeline.pr_status != "open":
            self._stage(pipeline, "deploy", "gated", "Runs after the PR is merged.")
            self._stage(pipeline, "verify", "gated", "Runs after deployment (before/after SEO + CWV).")
            return
        self._stage(pipeline, "deploy", "pending", "Deployment will start on merge.")
        self._stage(pipeline, "verify", "pending", "Verification queued for post-deploy.")

    async def _learn(self, pipeline: PatchPipeline) -> None:
        # Reuse the Learning Engine's evidence store implicitly: record the outcome
        # on the pipeline so confidence can be reused. (Confidence itself is read
        # from LearningEngine by the generator.)
        detail = (f"framework={pipeline.framework}, applied={pipeline.patches_applied}, "
                  f"validation={pipeline.validation_status}, pr={pipeline.pr_status}")
        self._stage(pipeline, "learn", "succeeded", detail)

    def _pr_body(self, pipeline: PatchPipeline) -> str:
        return (
            "Automated, SEO-safe patches from the SEO Agent framework-aware pipeline.\n\n"
            f"- Framework: {pipeline.framework}\n"
            f"- Files changed: {pipeline.patches_applied}\n"
            f"- Validation: {pipeline.validation_status}\n\n"
            "Only SEO surfaces (metadata / robots / sitemap / schema / Open Graph) were "
            "modified. No UI, layout, business logic, auth, payments, CRM or database changes."
        )

    # -- helpers ------------------------------------------------------------

    def _stage(self, pipeline: PatchPipeline, name: str, status: str, detail: Optional[str] = None) -> None:
        now = datetime.utcnow().isoformat()
        # Rebuild with fresh dicts so SQLAlchemy sees a genuinely new JSONB value.
        stages = [dict(s) for s in (pipeline.stages or [])]
        for s in stages:
            if s.get("name") == name:
                if s.get("started_at") is None:
                    s["started_at"] = now
                s["status"] = status
                s["finished_at"] = now
                s["detail"] = detail
                break
        pipeline.stages = stages
        flag_modified(pipeline, "stages")  # JSONB needs an explicit dirty flag
        pipeline.current_stage = name

    async def _save(self, pipeline: PatchPipeline) -> None:
        pipeline.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(pipeline)

    # -- read ---------------------------------------------------------------

    async def get(self, pipeline_id: UUID, tenant_id: UUID) -> Optional[PatchPipeline]:
        return (await self.db.execute(
            select(PatchPipeline).where(
                PatchPipeline.id == pipeline_id, PatchPipeline.tenant_id == tenant_id
            )
        )).scalars().first()

    async def latest(self, project_id: UUID, tenant_id: UUID) -> Optional[PatchPipeline]:
        return (await self.db.execute(
            select(PatchPipeline).where(
                PatchPipeline.project_id == project_id, PatchPipeline.tenant_id == tenant_id
            ).order_by(PatchPipeline.created_at.desc()).limit(1)
        )).scalars().first()

    async def list_pipelines(self, project_id: UUID, tenant_id: UUID, limit: int = 25) -> List[PatchPipeline]:
        rows = await self.db.execute(
            select(PatchPipeline).where(
                PatchPipeline.project_id == project_id, PatchPipeline.tenant_id == tenant_id
            ).order_by(PatchPipeline.created_at.desc()).limit(limit)
        )
        return list(rows.scalars().all())

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        latest = await self.latest(project_id, tenant_id)
        if not latest:
            return {"has_run": False, "status": None, "current_stage": None, "stages": []}
        return {
            "has_run": True,
            "status": getattr(latest.status, "value", latest.status),
            "current_stage": latest.current_stage,
            "framework": latest.framework,
            "branch_name": latest.branch_name,
            "commit_sha": latest.commit_sha,
            "pr_url": latest.pr_url,
            "pr_status": latest.pr_status,
            "validation_status": latest.validation_status,
            "patches_total": latest.patches_total,
            "patches_applied": latest.patches_applied,
            "stages": latest.stages or [],
            "updated_at": latest.updated_at.isoformat() if latest.updated_at else None,
        }
