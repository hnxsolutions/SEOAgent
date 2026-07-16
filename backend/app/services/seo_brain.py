"""SeoBrainService — the autonomous SEO master orchestrator.

This is a thin composition + intelligence layer. It does NOT re-implement any
module: it collects signals produced by the existing services (audit, robots,
sitemap, planner, indexing, search console, repo agent), classifies every issue
with app.brain.classifier, and produces (a) one prioritized master plan and
(b) a single Mission-Control brain state. Everything downstream (patch → PR)
still runs through the existing repo-agent with its human-approval gate.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brain.classifier import BrainIssue, classify
from app.models.audit import SEOIssue, SEOIssueStatus
from app.models.project import Project
from app.models.repo_agent import (
    PullRequestRecord,
    PullRequestStatus,
    RepoConnection,
    SeoCodeIssue as RepoCodeIssue,
    SeoCodePatch,
    SeoCodePatchStatus,
)
from app.models.robots import RobotsIssue, RobotsIssueStatus
from app.models.seo_run import SeoRun
from app.models.sitemap import SitemapIssue, SitemapIssueStatus
from app.models.planner import SeoTask, SeoTaskStatus

logger = structlog.get_logger(__name__)

_OPEN_TASK_STATUSES = [SeoTaskStatus.todo, SeoTaskStatus.in_progress, SeoTaskStatus.approved]


class SeoBrainService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- Master plan ---------------------------------------------------------

    async def get_master_plan(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> Dict[str, Any]:
        """Collect issues from every module, classify, and rank one plan."""
        project = await self._get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")

        issues = await self._collect_issues(project_id, tenant_id)
        items: List[Dict[str, Any]] = []
        for issue in issues:
            c = classify(issue)
            items.append({
                "source": issue.source,
                "issue_type": issue.issue_type,
                "title": issue.title,
                "url": issue.url,
                "reference_id": issue.reference_id,
                **c.as_dict(),
            })

        items.sort(key=lambda x: x["priority_score"], reverse=True)
        items = items[:limit]

        code_fixable = [i for i in items if i["code_fixable"]]
        by_category: Dict[str, int] = {}
        for i in items:
            by_category[i["category"]] = by_category.get(i["category"], 0) + 1

        return {
            "project_id": str(project_id),
            "total_issues": len(items),
            "code_fixable_count": len(code_fixable),
            "by_category": by_category,
            "top_priority": items[0] if items else None,
            "items": items,
        }

    # -- Brain state (Mission Control) --------------------------------------

    async def get_brain_state(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        project = await self._get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")

        latest_run = await self._latest_run(project_id, tenant_id)
        plan = await self.get_master_plan(project_id, tenant_id, limit=10)
        pending = await self._pending_approvals(project_id, tenant_id)
        modules = await self._module_summaries(project_id, tenant_id)

        health = self._health_score(plan, modules)
        current_stage, current_status = self._run_stage(latest_run)

        return {
            "project_id": str(project_id),
            "project_name": project.name,
            "domain": project.domain,
            "overall_health": health,
            "current_run": {
                "id": str(latest_run.id) if latest_run else None,
                "status": current_status,
                "current_stage": current_stage,
                "stage_statuses": getattr(latest_run, "stage_statuses", None) if latest_run else None,
            },
            "pending_approvals": pending,
            "master_plan_preview": plan["items"][:5],
            "master_plan_total": plan["total_issues"],
            "code_fixable_count": plan["code_fixable_count"],
            "next_action": self._next_action(plan, pending),
            "modules": modules,
        }

    # -- auto dispatch to the repo agent ------------------------------------

    async def get_repo_connection(self, project_id: UUID, tenant_id: UUID) -> Optional[RepoConnection]:
        """Most recent repository connection for the project, if any."""
        rows = await self.db.execute(
            select(RepoConnection).where(
                RepoConnection.project_id == project_id,
                RepoConnection.tenant_id == tenant_id,
            ).order_by(RepoConnection.created_at.desc()).limit(1)
        )
        return rows.scalars().first()

    async def get_pending_fixes(self, project_id: UUID, tenant_id: UUID, limit: int = 200) -> Dict[str, Any]:
        """Proposed patches awaiting human approval, enriched with SEO impact,
        confidence, before/after diff, traceability and a rollback strategy."""
        rows = await self.db.execute(
            select(SeoCodePatch).where(
                SeoCodePatch.project_id == project_id,
                SeoCodePatch.tenant_id == tenant_id,
                SeoCodePatch.status == SeoCodePatchStatus.proposed,
            ).order_by(SeoCodePatch.created_at.desc()).limit(limit)
        )
        patches = list(rows.scalars().all())

        # Load the originating code issues in one query for traceability.
        issue_ids = [p.issue_id for p in patches if p.issue_id]
        issues_by_id: Dict[Any, RepoCodeIssue] = {}
        if issue_ids:
            irows = await self.db.execute(
                select(RepoCodeIssue).where(RepoCodeIssue.id.in_(issue_ids))
            )
            issues_by_id = {i.id: i for i in irows.scalars().all()}

        # Evidence-based confidence (from verified past outcomes) overrides the
        # heuristic when enough history exists for a patch type.
        from app.services.learning import LearningEngine

        confidence_map = await LearningEngine(self.db).confidence_map(tenant_id)

        items = [
            self._enrich_patch(
                p,
                issues_by_id.get(p.issue_id),
                evidence_confidence=self._evidence_confidence(confidence_map, p),
            )
            for p in patches
        ]
        return {
            "project_id": str(project_id),
            "total": len(items),
            "items": items,
        }

    @staticmethod
    def _evidence_confidence(confidence_map: Dict[str, Any], patch: SeoCodePatch) -> Optional[int]:
        entry = confidence_map.get(SeoBrainService._enum(getattr(patch, "patch_type", "")))
        if entry and entry.get("evidence_based"):
            return entry.get("confidence")
        return None

    def _enrich_patch(
        self,
        patch: SeoCodePatch,
        issue: Optional[RepoCodeIssue],
        evidence_confidence: Optional[int] = None,
    ) -> Dict[str, Any]:
        issue_type = self._enum(getattr(issue, "issue_type", "")) if issue else self._enum(getattr(patch, "patch_type", ""))
        source = self._enum(getattr(issue, "source_reference_type", "")) if issue else "repo_scan"
        title = getattr(issue, "title", None) or f"Code fix: {self._enum(getattr(patch, 'patch_type', ''))}"
        c = classify(BrainIssue(
            source=source or "repo_scan",
            issue_type=issue_type or "",
            severity=self._enum(getattr(issue, "severity", "medium")) or "medium",
            title=title,
        ))
        return {
            "patch_id": str(patch.id),
            "status": self._enum(patch.status),
            "patch_type": self._enum(patch.patch_type),
            "file_path": patch.file_path,
            "affected_files": [patch.file_path],
            "issue": {
                "id": str(getattr(issue, "id", "")) if issue else None,
                "issue_type": issue_type,
                "title": title,
                "source": source,
                "source_reference_id": str(getattr(issue, "source_reference_id", "") or "") if issue else None,
            },
            # Patch-quality metadata required for admin review.
            "reason": patch.explanation,
            "seo_impact": c.impact,
            "expected_ranking_gain": c.expected_ranking_gain,
            "expected_traffic_gain": c.expected_traffic_gain,
            "confidence": evidence_confidence if evidence_confidence is not None else c.confidence,
            "confidence_source": "evidence" if evidence_confidence is not None else "heuristic",
            "category": c.category,
            "risk_level": self._enum(patch.risk_level),
            "diff": patch.diff_text,  # unified before/after
            "before_after_available": bool(patch.diff_text),
            "rollback_strategy": (
                "Applied on an isolated branch and opened as a PR; never merged automatically. "
                "To roll back: close the PR unmerged, or revert the commit if merged. The original "
                f"content hash ({(patch.original_content_hash or '')[:12]}) is stored to restore the "
                "pre-change file."
            ),
        }

    # -- issue collection (data only, no re-implemented logic) --------------

    async def _collect_issues(self, project_id: UUID, tenant_id: UUID) -> List[BrainIssue]:
        issues: List[BrainIssue] = []

        # Audit issues from the latest audit run for this project.
        latest_run = await self._latest_run(project_id, tenant_id)
        audit_id = getattr(latest_run, "audit_id", None) if latest_run else None
        if audit_id:
            rows = await self.db.execute(
                select(SEOIssue).where(
                    SEOIssue.audit_run_id == audit_id,
                    SEOIssue.tenant_id == tenant_id,
                    SEOIssue.status == SEOIssueStatus.open,
                ).limit(500)
            )
            for r in rows.scalars().all():
                issues.append(BrainIssue(
                    source="audit",
                    issue_type=r.issue_type or "",
                    severity=self._enum(r.severity),
                    category=self._enum(r.category),
                    title=r.title or "",
                    description=r.message or "",
                    url=r.url,
                    reference_id=str(r.id),
                ))

        # Robots issues (open).
        rows = await self.db.execute(
            select(RobotsIssue).where(
                RobotsIssue.project_id == project_id,
                RobotsIssue.tenant_id == tenant_id,
                RobotsIssue.status == RobotsIssueStatus.open,
            ).limit(200)
        )
        for r in rows.scalars().all():
            issues.append(BrainIssue(
                source="robots",
                issue_type=self._enum(r.issue_type),
                severity=self._enum(r.severity),
                title=r.title or "",
                description=r.description or "",
                reference_id=str(r.id),
            ))

        # Sitemap issues (open).
        rows = await self.db.execute(
            select(SitemapIssue).where(
                SitemapIssue.project_id == project_id,
                SitemapIssue.tenant_id == tenant_id,
                SitemapIssue.status == SitemapIssueStatus.open,
            ).limit(200)
        )
        for r in rows.scalars().all():
            issues.append(BrainIssue(
                source="sitemap",
                issue_type=self._enum(r.issue_type),
                severity=self._enum(r.severity),
                title=r.title or "",
                description=r.description or "",
                reference_id=str(r.id),
            ))

        return issues

    async def _module_summaries(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        summaries: Dict[str, Any] = {}

        # Planner: open task count + latest run.
        open_tasks = await self.db.execute(
            select(SeoTask).where(
                SeoTask.project_id == project_id,
                SeoTask.tenant_id == tenant_id,
                SeoTask.status.in_(_OPEN_TASK_STATUSES),
            ).limit(1000)
        )
        summaries["planner"] = {"open_tasks": len(list(open_tasks.scalars().all()))}

        # Robots + Sitemap + Indexing + Search Console via their own services,
        # each guarded so missing Google credentials degrade gracefully.
        summaries["robots"] = await self._safe_summary("robots", project_id, tenant_id)
        summaries["sitemap"] = await self._safe_summary("sitemap", project_id, tenant_id)
        summaries["indexing"] = await self._safe_summary("indexing", project_id, tenant_id)
        summaries["search_console"] = await self._safe_summary("search_console", project_id, tenant_id)
        return summaries

    async def _safe_summary(self, module: str, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        try:
            if module == "robots":
                from app.services.robots import RobotsIntelligenceService
                return await RobotsIntelligenceService(self.db).summary(project_id, tenant_id)
            if module == "sitemap":
                from app.services.sitemap import SitemapIntelligenceService
                issues = await SitemapIntelligenceService(self.db).list_issues(project_id, tenant_id)
                return {"status": "available", "open_issues": len(issues)}
            if module == "indexing":
                from app.services.indexing import IndexingService
                return await IndexingService(self.db).summary(project_id, tenant_id)
            if module == "search_console":
                from app.services.search_console import SearchConsoleService
                return await SearchConsoleService(self.db).summary(project_id, tenant_id)
        except Exception as exc:  # graceful degradation (e.g. GSC not connected)
            logger.info("brain_module_summary_unavailable", module=module, error=str(exc))
            return {"status": "unavailable", "reason": "not connected or no data"}
        return {"status": "no_data"}

    async def _pending_approvals(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        patches = await self.db.execute(
            select(SeoCodePatch).where(
                SeoCodePatch.project_id == project_id,
                SeoCodePatch.tenant_id == tenant_id,
                SeoCodePatch.status == SeoCodePatchStatus.proposed,
            ).limit(500)
        )
        prs = await self.db.execute(
            select(PullRequestRecord).where(
                PullRequestRecord.project_id == project_id,
                PullRequestRecord.tenant_id == tenant_id,
                PullRequestRecord.status == PullRequestStatus.open,
            ).limit(200)
        )
        return {
            "proposed_patches": len(list(patches.scalars().all())),
            "open_pull_requests": len(list(prs.scalars().all())),
        }

    # -- helpers -------------------------------------------------------------

    async def _get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        rows = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return rows.scalars().first()

    async def _latest_run(self, project_id: UUID, tenant_id: UUID) -> Optional[SeoRun]:
        rows = await self.db.execute(
            select(SeoRun).where(SeoRun.project_id == project_id, SeoRun.tenant_id == tenant_id)
            .order_by(SeoRun.created_at.desc()).limit(1)
        )
        return rows.scalars().first()

    @staticmethod
    def _enum(value) -> str:
        return getattr(value, "value", value) or ""

    @staticmethod
    def _run_stage(run: Optional[SeoRun]):
        if not run:
            return None, "none"
        return SeoBrainService._enum(getattr(run, "current_stage", None)) or None, SeoBrainService._enum(getattr(run, "status", None)) or "unknown"

    @staticmethod
    def _health_score(plan: Dict[str, Any], modules: Dict[str, Any]) -> int:
        """0-100 health: start at 100, subtract weighted priority of open issues."""
        score = 100.0
        for item in plan["items"]:
            weight = {"critical": 12, "high": 7, "medium": 3, "low": 1}.get(item["severity"], 2)
            score -= weight
        return max(0, min(100, round(score)))

    @staticmethod
    def _next_action(plan: Dict[str, Any], pending: Dict[str, Any]) -> str:
        if pending["open_pull_requests"]:
            return f"Review {pending['open_pull_requests']} open pull request(s) awaiting approval."
        if pending["proposed_patches"]:
            return f"Approve/reject {pending['proposed_patches']} proposed code patch(es)."
        top = plan.get("top_priority")
        if top:
            verb = "Generate a code fix for" if top["code_fixable"] else "Address"
            return f"{verb}: {top['title']} (priority {top['priority_score']})."
        return "No open issues. Run a full analysis to refresh the plan."
