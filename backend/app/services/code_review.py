"""Human approval workflow (Code Review).

The AI prepares a review (validate -> branch -> commit -> draft PR) and WAITS.
An admin reviews the generated files (old vs new diff, why, predicted impact,
risk) and explicitly Approves, Rejects, or Archives. Approve — and only Approve —
merges the pull request. Nothing merges automatically.

Reuses the framework patch generator, patch pipeline, verification engine,
notifications, and (for evidence-based confidence) the review outcomes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.code_review.analysis import build_file_review, estimate_impact, max_risk, risk_for_surface
from app.models.briefing import NotificationLevel
from app.models.code_review import CodeReview, CodeReviewStatus, ReviewRisk
from app.models.generated_patch import GeneratedPatchValidation, GeneratedSeoPatch
from app.models.patch_pipeline import PatchPipeline
from app.models.project import Project

logger = structlog.get_logger(__name__)


class CodeReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- prepare (validate -> ready_for_review) -----------------------------

    async def prepare(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Bundle the project's validated, SEO-safe patches into a review and
        mark it Ready For Review. Requires validation_status=passed and safe
        (safety + framework + static + SEO + git already enforced upstream)."""
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")

        patches = (await self.db.execute(
            select(GeneratedSeoPatch).where(
                GeneratedSeoPatch.project_id == project_id,
                GeneratedSeoPatch.tenant_id == tenant_id,
                GeneratedSeoPatch.safe.is_(True),
                GeneratedSeoPatch.validation_status == GeneratedPatchValidation.passed,
            )
        )).scalars().all()
        if not patches:
            return {"status": "nothing_to_review", "note": "No validated SEO-safe patches. Generate patches first."}

        surfaces = [p.surface for p in patches]
        overall_risk = max_risk([risk_for_surface(s) for s in surfaces])
        confidence = int(round(sum(p.confidence or 0 for p in patches) / max(len(patches), 1)))
        seo_before = next((p.seo_before for p in patches if p.seo_before is not None), None)
        impact = estimate_impact(surfaces, seo_before)

        pipeline = (await self.db.execute(
            select(PatchPipeline).where(
                PatchPipeline.project_id == project_id, PatchPipeline.tenant_id == tenant_id
            ).order_by(PatchPipeline.created_at.desc()).limit(1)
        )).scalars().first()

        technology = await self._technology_label(project_id, tenant_id)

        prior = (await self.db.execute(
            select(CodeReview).where(
                CodeReview.project_id == project_id, CodeReview.tenant_id == tenant_id,
                CodeReview.status == CodeReviewStatus.ready_for_review,
            )
        )).scalars().all()
        for r in prior:
            await self.db.delete(r)

        review = CodeReview(
            tenant_id=tenant_id, project_id=project_id,
            pipeline_id=(pipeline.id if pipeline else None),
            framework=(patches[0].framework if patches else None),
            technology=technology,
            status=CodeReviewStatus.ready_for_review,
            risk_level=overall_risk,
            confidence=confidence,
            files_count=len(patches),
            estimated_seo_impact=impact["seo_impact_label"],
            estimated_performance_impact=impact["performance_impact_label"],
            seo_before=impact["seo_before"],
            seo_after_predicted=impact["seo_after_predicted"],
            pr_url=(pipeline.pr_url if pipeline else None),
            pr_status=(pipeline.pr_status if pipeline else None),
            commit_sha=(pipeline.commit_sha if pipeline else None),
            patch_ids=[str(p.id) for p in patches],
        )
        self.db.add(review)
        await self.db.commit()
        await self.db.refresh(review)

        await self._notify(tenant_id, project_id, NotificationLevel.info, "Review needed",
                           f"{len(patches)} SEO-safe patch(es) for {review.framework} are ready for your review.",
                           category="code_review", dedupe_key=f"review-ready-{review.id}")
        logger.info("code_review_prepared", review_id=str(review.id), files=len(patches), risk=overall_risk.value)
        return {"status": "ready_for_review", "review_id": str(review.id), "files": len(patches),
                "risk": overall_risk.value}

    # -- read ---------------------------------------------------------------

    async def list_reviews(self, tenant_id: UUID, status: Optional[str] = None, project_id: Optional[UUID] = None,
                           limit: int = 100) -> List[CodeReview]:
        query = select(CodeReview).where(CodeReview.tenant_id == tenant_id)
        if status:
            query = query.where(CodeReview.status == CodeReviewStatus(status))
        if project_id:
            query = query.where(CodeReview.project_id == project_id)
        rows = await self.db.execute(query.order_by(CodeReview.created_at.desc()).limit(limit))
        return list(rows.scalars().all())

    async def get(self, review_id: UUID, tenant_id: UUID) -> Optional[CodeReview]:
        return (await self.db.execute(
            select(CodeReview).where(CodeReview.id == review_id, CodeReview.tenant_id == tenant_id)
        )).scalars().first()

    async def detail(self, review_id: UUID, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        review = await self.get(review_id, tenant_id)
        if not review:
            return None
        ids = [UUID(x) for x in (review.patch_ids or [])]
        patches = []
        if ids:
            patches = (await self.db.execute(
                select(GeneratedSeoPatch).where(GeneratedSeoPatch.id.in_(ids))
            )).scalars().all()
        files = [build_file_review(p, review.framework, review.seo_before) for p in patches]
        return {"review": self._shape(review), "files": files}

    # -- admin actions ------------------------------------------------------

    async def approve(self, review_id: UUID, tenant_id: UUID, admin: str) -> Dict[str, Any]:
        """ADMIN action — the only path that merges. Never called automatically."""
        review = await self.get(review_id, tenant_id)
        if not review:
            raise ValueError("Review not found")
        if review.status not in (CodeReviewStatus.ready_for_review, CodeReviewStatus.approved):
            return {"status": review.status.value, "note": "Review is not open for approval."}

        review.approved_by = admin
        review.approved_at = datetime.utcnow()
        review.status = CodeReviewStatus.approved

        merged = False
        if review.pr_url and settings.GITHUB_TOKEN:
            try:
                review.merge_sha = await self._merge_pr(review.pr_url, settings.GITHUB_TOKEN)
                review.status = CodeReviewStatus.merged
                review.pr_status = "merged"
                review.deployment_status = "pending"
                merged = True
            except Exception as exc:
                review.deployment_status = f"merge_failed: {str(exc)[:120]}"
                logger.warning("code_review_merge_failed", review_id=str(review_id), error=str(exc))
        else:
            review.deployment_status = "gated"  # honest: needs a connected repo + GITHUB_TOKEN to merge

        await self.db.commit()
        await self.db.refresh(review)

        # Continue the loop automatically: verify the deployed/live site. Runs the
        # measurable parts (live site + PageSpeed + SEO before/after + learning)
        # even when merge is gated, so the admin gets real evidence. Best-effort.
        await self._trigger_post_merge(review, tenant_id)

        await self._notify(tenant_id, review.project_id, NotificationLevel.success,
                           "Patch approved" + (" & merged" if merged else ""),
                           f"{admin} approved review {review_id}." + ("" if merged else " Merge is gated until a repo + GITHUB_TOKEN are connected."),
                           category="code_review")
        logger.info("code_review_approved", review_id=str(review_id), admin=admin, merged=merged)
        return {"status": review.status.value, "merged": merged, "merge_sha": review.merge_sha,
                "deployment_status": review.deployment_status}

    async def reject(self, review_id: UUID, tenant_id: UUID, admin: str, reason: str) -> Dict[str, Any]:
        review = await self.get(review_id, tenant_id)
        if not review:
            raise ValueError("Review not found")
        review.status = CodeReviewStatus.rejected
        review.rejected_by = admin
        review.rejected_at = datetime.utcnow()
        review.rejection_reason = (reason or "")[:2000]
        await self.db.commit()
        await self._notify(tenant_id, review.project_id, NotificationLevel.warning, "Patch rejected",
                           f"{admin} rejected review {review_id}: {(reason or '')[:120]}", category="code_review")
        # Learning: rejection is negative evidence for this framework — the patch
        # generator's confidence reads the approved/rejected ratio (framework_evidence).
        logger.info("code_review_rejected", review_id=str(review_id), admin=admin)
        return {"status": "rejected"}

    async def archive(self, review_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        review = await self.get(review_id, tenant_id)
        if not review:
            raise ValueError("Review not found")
        review.status = CodeReviewStatus.archived
        await self.db.commit()
        return {"status": "archived"}

    # -- learning evidence (reused by the generator's confidence) -----------

    async def framework_evidence(self, tenant_id: UUID, framework: str) -> Dict[str, int]:
        """Approved vs rejected counts for a framework — evidence for confidence."""
        rows = (await self.db.execute(
            select(CodeReview.status, func.count(CodeReview.id)).where(
                CodeReview.tenant_id == tenant_id, CodeReview.framework == framework,
            ).group_by(CodeReview.status)
        )).all()
        counts = {getattr(s, "value", s): int(c) for s, c in rows}
        approved = counts.get("approved", 0) + counts.get("merged", 0)
        rejected = counts.get("rejected", 0)
        return {"approved": approved, "rejected": rejected}

    # -- dashboards ---------------------------------------------------------

    async def mission_control_summary(self, tenant_id: UUID) -> Dict[str, Any]:
        reviews = (await self.db.execute(
            select(CodeReview).where(CodeReview.tenant_id == tenant_id)
            .order_by(CodeReview.created_at.desc()).limit(500)
        )).scalars().all()
        today = datetime.utcnow().date()
        pending = [r for r in reviews if r.status == CodeReviewStatus.ready_for_review]
        approved_today = [r for r in reviews if r.approved_at and r.approved_at.date() == today]
        rejected_today = [r for r in reviews if r.rejected_at and r.rejected_at.date() == today]

        def avg_minutes(rs, end_attr):
            deltas = [((getattr(r, end_attr) - r.created_at).total_seconds() / 60)
                      for r in rs if getattr(r, end_attr) and r.created_at]
            return round(sum(deltas) / len(deltas), 1) if deltas else None

        decided = [r for r in reviews if r.status in (CodeReviewStatus.approved, CodeReviewStatus.merged, CodeReviewStatus.rejected)]
        merged = [r for r in reviews if r.merge_sha and r.approved_at]
        confidences = [r.confidence for r in reviews if r.confidence is not None]
        risk_counts: Dict[str, int] = {}
        for r in reviews:
            risk_counts[r.risk_level.value] = risk_counts.get(r.risk_level.value, 0) + 1
        return {
            "pending_reviews": len(pending),
            "approved_today": len(approved_today),
            "rejected_today": len(rejected_today),
            "average_review_time_minutes": avg_minutes(decided, "approved_at") or avg_minutes(decided, "rejected_at"),
            "average_merge_time_minutes": avg_minutes(merged, "approved_at"),
            "average_confidence": round(sum(confidences) / len(confidences)) if confidences else None,
            "risk_breakdown": risk_counts,
        }

    async def briefing_summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        reviews = (await self.db.execute(
            select(CodeReview).where(
                CodeReview.tenant_id == tenant_id, CodeReview.project_id == project_id
            ).order_by(CodeReview.created_at.desc()).limit(100)
        )).scalars().all()
        return {
            "pending_reviews": sum(1 for r in reviews if r.status == CodeReviewStatus.ready_for_review),
            "waiting_for_approval": [self._shape(r) for r in reviews if r.status == CodeReviewStatus.ready_for_review][:5],
            "recently_merged": [self._shape(r) for r in reviews if r.status == CodeReviewStatus.merged][:5],
            "recently_rejected": [self._shape(r) for r in reviews if r.status == CodeReviewStatus.rejected][:5],
            "top_high_risk": [self._shape(r) for r in reviews
                              if r.risk_level in (ReviewRisk.high, ReviewRisk.medium)
                              and r.status == CodeReviewStatus.ready_for_review][:5],
        }

    # -- helpers ------------------------------------------------------------

    async def _technology_label(self, project_id: UUID, tenant_id: UUID) -> Optional[str]:
        try:
            from app.services.fingerprint import FingerprintService

            s = await FingerprintService(self.db).summary(project_id, tenant_id)
            parts = [s.get("primary_framework"), s.get("primary_language"), s.get("hosting")]
            return " · ".join(p for p in parts if p) or None
        except Exception:
            return None

    async def _trigger_post_merge(self, review: CodeReview, tenant_id: UUID) -> None:
        """Continue the loop automatically: run the post-merge verification
        pipeline (detect deployment -> verify live site -> PageSpeed / CWV ->
        Search Console -> compare before/after -> learning). Measures the REAL
        deployed site; merge/deploy/GSC steps degrade gracefully. Best-effort:
        never breaks the approve response."""
        try:
            from app.services.verification_pipeline import VerificationPipelineService

            review.deployment_status = review.deployment_status or "verifying"
            await self.db.commit()
            await VerificationPipelineService(self.db).run(review.project_id, tenant_id, review_id=review.id)
        except Exception as exc:
            logger.warning("code_review_post_merge_failed", review_id=str(review.id), error=str(exc))

    async def _merge_pr(self, pr_url: str, token: str) -> str:
        """Merge a GitHub PR via the REST API. Returns the merge commit SHA."""
        import re

        m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url or "")
        if not m:
            raise ValueError("Unrecognised PR URL")
        owner, repo, number = m.group(1), m.group(2), m.group(3)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge",
                json={"merge_method": "squash"}, headers=headers,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub merge failed ({resp.status_code})")
        return resp.json().get("sha", "")

    async def _notify(self, tenant_id, project_id, level, title, message, *, category="code_review", dedupe_key=None):
        try:
            from app.services.notifications import NotificationService

            await NotificationService(self.db).create(
                tenant_id, level, title, message, project_id=project_id,
                category=category, dedupe_key=dedupe_key,
            )
        except Exception:
            pass

    @staticmethod
    def _shape(r: CodeReview) -> Dict[str, Any]:
        return {
            "id": str(r.id),
            "project_id": str(r.project_id),
            "framework": r.framework,
            "technology": r.technology,
            "status": r.status.value,
            "risk_level": r.risk_level.value,
            "confidence": r.confidence,
            "files_count": r.files_count,
            "estimated_seo_impact": r.estimated_seo_impact,
            "estimated_performance_impact": r.estimated_performance_impact,
            "seo_before": r.seo_before,
            "seo_after_predicted": r.seo_after_predicted,
            "pr_url": r.pr_url,
            "pr_status": r.pr_status,
            "commit_sha": r.commit_sha,
            "merge_sha": r.merge_sha,
            "deployment_status": r.deployment_status,
            "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "rejected_by": r.rejected_by,
            "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
            "rejection_reason": r.rejection_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
