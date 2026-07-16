"""Self-learning / confidence engine.

Aggregates AiFixVerification outcomes into evidence-based confidence per patch
type and project-level learning statistics. Confidence is derived only from
observed verification results — never fabricated. When there is not yet enough
evidence for a patch type, callers fall back to the heuristic classifier.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification import AiFixVerification, VerificationStatus


# Minimum finalized verifications before evidence overrides the heuristic.
MIN_EVIDENCE = 3

_SUCCESS = VerificationStatus.verified_success
_PARTIAL = VerificationStatus.partially_successful
_FAILED = VerificationStatus.failed
_TERMINAL = [_SUCCESS, _PARTIAL, _FAILED, VerificationStatus.needs_human_review]


class LearningEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def evidence_confidence(self, patch_type: str, tenant_id: UUID) -> Optional[int]:
        """Evidence-based confidence (0-100) for a patch type, or None when
        there is not enough history to be meaningful."""
        rows = (await self.db.execute(
            select(AiFixVerification.status, func.count(AiFixVerification.id))
            .where(
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.patch_type == patch_type,
                AiFixVerification.status.in_(_TERMINAL),
            ).group_by(AiFixVerification.status)
        )).all()
        counts = {self._enum(s): int(c) for s, c in rows}
        success = counts.get(_SUCCESS.value, 0)
        partial = counts.get(_PARTIAL.value, 0)
        failed = counts.get(_FAILED.value, 0)
        total = success + partial + failed
        if total < MIN_EVIDENCE:
            return None
        # Partial successes count as half credit.
        score = (success + 0.5 * partial) / total
        return int(round(score * 100))

    async def confidence_map(self, tenant_id: UUID) -> Dict[str, Dict[str, Any]]:
        """Per-patch-type evidence summary for the dashboard confidence panel."""
        rows = (await self.db.execute(
            select(
                AiFixVerification.patch_type,
                AiFixVerification.status,
                func.count(AiFixVerification.id),
            )
            .where(
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status.in_(_TERMINAL),
            )
            .group_by(AiFixVerification.patch_type, AiFixVerification.status)
        )).all()
        agg: Dict[str, Dict[str, int]] = {}
        for patch_type, status, count in rows:
            bucket = agg.setdefault(patch_type, {})
            bucket[self._enum(status)] = int(count)
        out: Dict[str, Dict[str, Any]] = {}
        for patch_type, bucket in agg.items():
            success = bucket.get(_SUCCESS.value, 0)
            partial = bucket.get(_PARTIAL.value, 0)
            failed = bucket.get(_FAILED.value, 0)
            total = success + partial + failed
            confidence = int(round((success + 0.5 * partial) / total * 100)) if total else None
            out[patch_type] = {
                "success": success,
                "partial": partial,
                "failed": failed,
                "total": total,
                "confidence": confidence,
                "evidence_based": total >= MIN_EVIDENCE,
            }
        return out

    async def learning_stats(self, tenant_id: UUID, project_id: Optional[UUID] = None) -> Dict[str, Any]:
        base = select(AiFixVerification).where(AiFixVerification.tenant_id == tenant_id)
        if project_id:
            base = base.where(AiFixVerification.project_id == project_id)
        verifs = (await self.db.execute(base)).scalars().all()

        by_status: Dict[str, int] = {}
        improvements: List[float] = []
        for v in verifs:
            key = self._enum(v.status)
            by_status[key] = by_status.get(key, 0) + 1
            if v.improvement_pct is not None:
                improvements.append(v.improvement_pct)

        finalized = sum(by_status.get(s.value, 0) for s in _TERMINAL)
        success = by_status.get(_SUCCESS.value, 0)
        cmap = await self.confidence_map(tenant_id)
        ranked = sorted(
            [(k, m) for k, m in cmap.items() if m["total"] > 0],
            key=lambda kv: (kv[1]["confidence"] or 0),
            reverse=True,
        )
        return {
            "total_verifications": len(verifs),
            "finalized": finalized,
            "by_status": by_status,
            "success_rate": round(success / finalized * 100, 1) if finalized else None,
            "average_improvement_pct": round(sum(improvements) / len(improvements), 1) if improvements else None,
            "most_successful_fixes": [{"patch_type": k, **m} for k, m in ranked[:5]],
            "least_successful_fixes": [{"patch_type": k, **m} for k, m in ranked[-5:][::-1]] if len(ranked) > 1 else [],
            "confidence_by_patch_type": cmap,
        }

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
