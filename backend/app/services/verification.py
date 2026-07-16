"""After-merge verification engine.

When a pull request created by the repo agent is merged, this engine enqueues a
verification per applied patch, later runs a fresh SEO analysis (reusing
SeoRunService — no crawl/audit logic re-implemented), and compares the new audit
against the baseline the fix was generated from to decide whether the fix
actually worked. Results feed the learning/confidence engine.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit import SEOAuditRun, SEOIssue
from app.models.repo_agent import (
    PatchApplyResult,
    PatchApplyResultStatus,
    PullRequestRecord,
    PullRequestStatus,
    SeoCodeIssue,
    SeoCodePatch,
)
from app.models.seo_run import SeoRun, SeoRunStatus
from app.models.verification import AiFixVerification, VerificationStatus

logger = structlog.get_logger(__name__)


class VerificationEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- enqueue on merge ----------------------------------------------------

    async def mark_pr_merged(
        self,
        pull_request_id: UUID,
        tenant_id: UUID,
        delay_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Mark a PR merged and enqueue verification for its applied patches.

        This is the single entry point used both by a real merge webhook (future)
        and by the admin 'simulate merge' action. Idempotent per patch.
        """
        pr = (await self.db.execute(
            select(PullRequestRecord).where(
                PullRequestRecord.id == pull_request_id,
                PullRequestRecord.tenant_id == tenant_id,
            )
        )).scalars().first()
        if not pr:
            raise ValueError("Pull request not found")

        pr.status = PullRequestStatus.merged
        merged_at = datetime.utcnow()

        delay = settings.VERIFICATION_DELAY_MINUTES if delay_minutes is None else delay_minutes
        scheduled_at = merged_at + timedelta(minutes=max(0, delay))

        # applied patches in this PR's apply run
        applied = (await self.db.execute(
            select(PatchApplyResult).where(
                PatchApplyResult.apply_run_id == pr.apply_run_id,
                PatchApplyResult.status == PatchApplyResultStatus.applied,
            )
        )).scalars().all()

        enqueued = 0
        for result in applied:
            existing = (await self.db.execute(
                select(AiFixVerification).where(
                    AiFixVerification.patch_id == result.patch_id,
                    AiFixVerification.pull_request_id == pr.id,
                )
            )).scalars().first()
            if existing:
                continue
            patch = (await self.db.execute(
                select(SeoCodePatch).where(SeoCodePatch.id == result.patch_id)
            )).scalars().first()
            if not patch:
                continue
            issue = None
            if patch.issue_id:
                issue = (await self.db.execute(
                    select(SeoCodeIssue).where(SeoCodeIssue.id == patch.issue_id)
                )).scalars().first()

            baseline_run = await self._latest_completed_run(pr.project_id, tenant_id)
            self.db.add(AiFixVerification(
                tenant_id=tenant_id,
                project_id=pr.project_id,
                patch_id=patch.id,
                pull_request_id=pr.id,
                issue_id=patch.issue_id,
                patch_type=self._enum(getattr(patch, "patch_type", "")),
                issue_type=self._enum(getattr(issue, "issue_type", "")) if issue else None,
                status=VerificationStatus.pending,
                scheduled_at=scheduled_at,
                baseline_seo_run_id=getattr(baseline_run, "id", None),
                baseline_score=await self._run_score(baseline_run),
                merged_at=merged_at,
            ))
            enqueued += 1

        await self.db.commit()
        logger.info("verification_enqueued", pr_id=str(pr.id), enqueued=enqueued, scheduled_at=scheduled_at.isoformat())
        return {"pull_request_id": str(pr.id), "status": "merged", "verifications_enqueued": enqueued,
                "scheduled_at": scheduled_at.isoformat()}

    # -- automation (called by the scheduler) --------------------------------

    async def run_due_verifications(self, tenant_id: Optional[UUID] = None, now: Optional[datetime] = None, limit: int = 25) -> Dict[str, Any]:
        """Start a follow-up SEO run for each project with due pending
        verifications, then reconcile any whose follow-up run has completed."""
        from app.services.seo_run import SeoRunService  # local import avoids cycle

        now = now or datetime.utcnow()
        query = select(AiFixVerification).where(
            AiFixVerification.status == VerificationStatus.pending,
            AiFixVerification.scheduled_at <= now,
        )
        if tenant_id:
            query = query.where(AiFixVerification.tenant_id == tenant_id)
        due = (await self.db.execute(query.limit(limit))).scalars().all()

        started_projects = 0
        by_project: Dict[Any, List[AiFixVerification]] = {}
        for v in due:
            by_project.setdefault((v.project_id, v.tenant_id), []).append(v)

        run_service = SeoRunService(self.db)
        started_runs: List[Dict[str, str]] = []
        for (project_id, ten), verifs in by_project.items():
            try:
                run = await run_service.start_run(project_id, ten)
            except Exception:
                logger.exception("verification_followup_run_failed", project_id=str(project_id))
                continue
            for v in verifs:
                v.status = VerificationStatus.running
                v.followup_seo_run_id = run.id
            await self.db.commit()
            started_projects += 1
            started_runs.append({"run_id": str(run.id), "tenant_id": str(ten)})

        # The caller executes each started run (reusing run_seo_run_background),
        # then calls reconcile_running_verifications once they complete.
        return {"followup_runs_started": started_projects, "started_runs": started_runs}

    async def reconcile_running_verifications(self, tenant_id: Optional[UUID] = None, limit: int = 100) -> int:
        """Finalize verifications whose follow-up SEO run has completed."""
        query = select(AiFixVerification).where(AiFixVerification.status == VerificationStatus.running)
        if tenant_id:
            query = query.where(AiFixVerification.tenant_id == tenant_id)
        running = (await self.db.execute(query.limit(limit))).scalars().all()

        finalized = 0
        for v in running:
            followup = None
            if v.followup_seo_run_id:
                followup = (await self.db.execute(
                    select(SeoRun).where(SeoRun.id == v.followup_seo_run_id)
                )).scalars().first()
            if not followup or self._enum(followup.status) != SeoRunStatus.completed.value:
                continue
            baseline = None
            if v.baseline_seo_run_id:
                baseline = (await self.db.execute(
                    select(SeoRun).where(SeoRun.id == v.baseline_seo_run_id)
                )).scalars().first()
            await self._finalize(v, baseline, followup)
            finalized += 1
        if finalized:
            await self.db.commit()
        return finalized

    async def verify_now(self, verification_id: UUID, tenant_id: UUID) -> AiFixVerification:
        """Force-run a verification's comparison against the latest completed run
        (used for tests and manual re-checks)."""
        v = (await self.db.execute(
            select(AiFixVerification).where(
                AiFixVerification.id == verification_id, AiFixVerification.tenant_id == tenant_id
            )
        )).scalars().first()
        if not v:
            raise ValueError("Verification not found")
        followup = await self._latest_completed_run(v.project_id, tenant_id)
        baseline = None
        if v.baseline_seo_run_id:
            baseline = (await self.db.execute(
                select(SeoRun).where(SeoRun.id == v.baseline_seo_run_id)
            )).scalars().first()
        if followup is not None and getattr(baseline, "id", None) == followup.id:
            baseline = None  # need a distinct later run to compare against
        v.followup_seo_run_id = getattr(followup, "id", None)
        await self._finalize(v, baseline, followup)
        await self.db.commit()
        await self.db.refresh(v)
        return v

    # -- comparison ----------------------------------------------------------

    async def _finalize(self, v: AiFixVerification, baseline: Optional[SeoRun], followup: Optional[SeoRun]) -> None:
        base_snap = await self._audit_snapshot(baseline)
        after_snap = await self._audit_snapshot(followup)

        v.baseline_score = base_snap["score"]
        v.followup_score = after_snap["score"]
        v.verified_at = datetime.utcnow()

        # Map the fixed issue to an audit category and check whether that
        # category's issue count fell.
        category = self._category_for(v.issue_type or v.patch_type)
        base_cat = base_snap["by_category"].get(category, 0)
        after_cat = after_snap["by_category"].get(category, 0)
        issue_resolved = after_cat < base_cat if base_cat else (after_cat == 0)
        v.issue_resolved = bool(issue_resolved)

        base_total = base_snap["total"]
        after_total = after_snap["total"]
        resolved_types = sorted(set(k for k, c in base_snap["by_category"].items()
                                    if c > after_snap["by_category"].get(k, 0)))
        new_types = sorted(set(k for k, c in after_snap["by_category"].items()
                               if c > base_snap["by_category"].get(k, 0)))

        score_delta = None
        if v.baseline_score is not None and v.followup_score is not None:
            score_delta = v.followup_score - v.baseline_score
            if v.baseline_score:
                v.improvement_pct = round(score_delta / v.baseline_score * 100, 1)
            else:
                v.improvement_pct = None

        v.details = {
            "category_checked": category,
            "baseline_category_issues": base_cat,
            "followup_category_issues": after_cat,
            "baseline_total_issues": base_total,
            "followup_total_issues": after_total,
            "baseline_score": v.baseline_score,
            "followup_score": v.followup_score,
            "score_delta": score_delta,
            "resolved_categories": resolved_types,
            "new_categories": new_types,
            "regression": bool(new_types) or (score_delta is not None and score_delta < 0),
            "comparable": baseline is not None and followup is not None,
        }
        v.status = self._decide_status(v, score_delta, issue_resolved, bool(new_types), comparable=baseline is not None and followup is not None)

    @staticmethod
    def _decide_status(v, score_delta, issue_resolved, has_regression, *, comparable) -> VerificationStatus:
        if not comparable:
            return VerificationStatus.needs_human_review
        improved = score_delta is not None and score_delta > 0
        flat = score_delta is not None and score_delta == 0
        if issue_resolved and improved and not has_regression:
            return VerificationStatus.verified_success
        if issue_resolved and (flat or improved):
            return VerificationStatus.partially_successful
        if not issue_resolved and (score_delta is not None and score_delta < 0):
            return VerificationStatus.failed
        return VerificationStatus.needs_human_review

    async def _audit_snapshot(self, run: Optional[SeoRun]) -> Dict[str, Any]:
        if not run or not getattr(run, "audit_id", None):
            return {"score": None, "total": 0, "by_category": {}}
        audit = (await self.db.execute(
            select(SEOAuditRun).where(SEOAuditRun.id == run.audit_id)
        )).scalars().first()
        rows = (await self.db.execute(
            select(SEOIssue.category, func.count(SEOIssue.id))
            .where(SEOIssue.audit_run_id == run.audit_id)
            .group_by(SEOIssue.category)
        )).all()
        by_category = {self._enum(cat): int(count) for cat, count in rows}
        return {
            "score": float(audit.site_score) if audit and audit.site_score is not None else None,
            "total": sum(by_category.values()),
            "by_category": by_category,
        }

    # -- queries for the API -------------------------------------------------

    async def get_queue(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> List[AiFixVerification]:
        rows = await self.db.execute(
            select(AiFixVerification).where(
                AiFixVerification.project_id == project_id,
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status.in_([VerificationStatus.pending, VerificationStatus.running]),
            ).order_by(AiFixVerification.scheduled_at.asc()).limit(limit)
        )
        return list(rows.scalars().all())

    async def get_history(self, project_id: UUID, tenant_id: UUID, limit: int = 100) -> List[AiFixVerification]:
        rows = await self.db.execute(
            select(AiFixVerification).where(
                AiFixVerification.project_id == project_id,
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status.notin_([VerificationStatus.pending, VerificationStatus.running]),
            ).order_by(AiFixVerification.verified_at.desc().nullslast()).limit(limit)
        )
        return list(rows.scalars().all())

    # -- helpers -------------------------------------------------------------

    async def _latest_completed_run(self, project_id: UUID, tenant_id: UUID) -> Optional[SeoRun]:
        return (await self.db.execute(
            select(SeoRun).where(
                SeoRun.project_id == project_id,
                SeoRun.tenant_id == tenant_id,
                SeoRun.status == SeoRunStatus.completed,
            ).order_by(SeoRun.completed_at.desc().nullslast()).limit(1)
        )).scalars().first()

    async def _run_score(self, run: Optional[SeoRun]) -> Optional[float]:
        snap = await self._audit_snapshot(run)
        return snap["score"]

    @staticmethod
    def _category_for(type_str: str) -> str:
        t = (type_str or "").lower()
        if any(k in t for k in ("schema", "json_ld", "structured", "faq", "breadcrumb")):
            return "structured_data"
        if any(k in t for k in ("robot", "sitemap", "canonical", "index", "crawl")):
            return "technical"
        if any(k in t for k in ("link",)):
            return "links"
        if any(k in t for k in ("image", "alt", "performance", "speed")):
            return "performance"
        return "metadata"

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
