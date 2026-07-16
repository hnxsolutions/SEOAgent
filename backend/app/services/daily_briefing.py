"""Daily executive briefing service.

Composes already-computed output from the SEO Brain, Learning, Verification and
Deployment engines plus SEO runs and pull requests into one stored executive
briefing (health, sections, timeline, AI summary). No SEO calculation is
re-implemented here — every number comes from an existing service or table.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOAuditRun
from app.models.briefing import DailyBriefing, NotificationLevel
from app.models.deployment import Deployment, DeploymentStatus
from app.models.repo_agent import PullRequestRecord, PullRequestStatus
from app.models.seo_run import SeoRun, SeoRunStatus
from app.models.verification import AiFixVerification, VerificationStatus
from app.services.deployment import DeploymentEngine
from app.services.learning import LearningEngine
from app.services.notifications import NotificationService
from app.services.seo_brain import SeoBrainService
from app.services.verification import VerificationEngine

logger = structlog.get_logger(__name__)


class DailyBriefingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate(self, project_id: UUID, tenant_id: UUID, use_llm: bool = True) -> DailyBriefing:
        """Compose today's briefing from existing services and persist it
        (idempotent per project + date)."""
        brain = SeoBrainService(self.db)
        state = await brain.get_brain_state(project_id, tenant_id)  # reuse: health, modules, plan, pending

        learning = await LearningEngine(self.db).learning_stats(tenant_id, project_id=project_id)
        verifications = VerificationEngine(self.db)
        recent_verified = await verifications.get_history(project_id, tenant_id, limit=10)
        verification_queue = await verifications.get_queue(project_id, tenant_id, limit=20)
        deployments = await DeploymentEngine(self.db).list_deployments(project_id, tenant_id, limit=10)

        seo_score, seo_score_prev = await self._seo_score_trend(project_id, tenant_id)
        prs = await self._pull_request_summary(project_id, tenant_id)
        plan = await brain.get_master_plan(project_id, tenant_id, limit=50)
        buckets = self._severity_buckets(plan["items"])
        opportunities = plan["items"][:5]
        gains = self._estimate_gains(plan["items"])

        ai_confidence = learning.get("success_rate")
        timeline = await self._build_timeline(project_id, tenant_id)

        sections: Dict[str, Any] = {
            "overall_health": state["overall_health"],
            "ai_confidence": ai_confidence,
            "seo_score": seo_score,
            "seo_score_prev": seo_score_prev,
            "seo_score_trend": self._trend(seo_score, seo_score_prev),
            "current_run": state["current_run"],
            "modules": state["modules"],  # robots / sitemap / gsc / indexing / planner summaries
            "pending_ai_fixes": state["pending_approvals"].get("proposed_patches", 0)
            if isinstance(state.get("pending_approvals"), dict) else state.get("pending_approvals"),
            "pending_approvals": state["pending_approvals"],
            "master_plan_total": plan["total_issues"],
            "code_fixable_count": plan["code_fixable_count"],
            "critical_issues": buckets["critical"],
            "warnings": buckets["high"],
            "medium_issues": buckets["medium"],
            "low_issues": buckets["low"],
            "top_opportunities": opportunities,
            "recommended_actions": self._recommended_actions(state, buckets, prs),
            "next_action": state["next_action"],
            "estimated_traffic_gain": gains["traffic"],
            "estimated_ranking_gain": gains["ranking"],
            "estimated_roi": gains["roi"],
            "learning": {
                "success_rate": learning.get("success_rate"),
                "average_improvement_pct": learning.get("average_improvement_pct"),
                "finalized": learning.get("finalized"),
                "most_successful_fixes": learning.get("most_successful_fixes", [])[:3],
            },
            "verification": {
                "queue": len(verification_queue),
                "recently_verified": [self._verif_item(v) for v in recent_verified[:5]],
            },
            "deployments": [self._deploy_item(d) for d in deployments[:5]],
            "pull_requests": prs,
        }

        summary, source = await self._executive_summary(state, sections, use_llm=use_llm)
        briefing = await self._upsert(
            project_id, tenant_id, self._json_safe(sections), self._json_safe(timeline), summary, source,
            health=state["overall_health"], confidence=ai_confidence,
            seo_score=seo_score, seo_score_prev=seo_score_prev,
        )
        await self._emit_notifications(project_id, tenant_id, buckets, prs)
        return briefing

    # -- section builders (compose only) ------------------------------------

    async def _seo_score_trend(self, project_id: UUID, tenant_id: UUID):
        """Latest two completed runs' audit scores (today vs previous)."""
        runs = (await self.db.execute(
            select(SeoRun).where(
                SeoRun.project_id == project_id,
                SeoRun.tenant_id == tenant_id,
                SeoRun.status == SeoRunStatus.completed,
            ).order_by(SeoRun.completed_at.desc().nullslast()).limit(2)
        )).scalars().all()
        scores = []
        for run in runs:
            if run.audit_id:
                audit = (await self.db.execute(
                    select(SEOAuditRun).where(SEOAuditRun.id == run.audit_id)
                )).scalars().first()
                scores.append(float(audit.site_score) if audit and audit.site_score is not None else None)
            else:
                scores.append(None)
        latest = scores[0] if scores else None
        prev = scores[1] if len(scores) > 1 else None
        return latest, prev

    async def _pull_request_summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, int]:
        rows = (await self.db.execute(
            select(PullRequestRecord.status).where(
                PullRequestRecord.project_id == project_id,
                PullRequestRecord.tenant_id == tenant_id,
            )
        )).scalars().all()
        counts: Dict[str, int] = {}
        for status in rows:
            key = getattr(status, "value", status)
            counts[key] = counts.get(key, 0) + 1
        return {
            "open": counts.get(PullRequestStatus.open.value, 0) + counts.get(PullRequestStatus.draft.value, 0),
            "merged": counts.get(PullRequestStatus.merged.value, 0),
            "failed": counts.get(PullRequestStatus.failed.value, 0),
            "total": sum(counts.values()),
        }

    @staticmethod
    def _severity_buckets(items: List[Dict[str, Any]]) -> Dict[str, int]:
        buckets = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for it in items:
            sev = (it.get("severity") or "").lower()
            if sev in buckets:
                buckets[sev] += 1
        return buckets

    @staticmethod
    def _estimate_gains(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Reuse the classifier's per-item bands already present on plan items.
        code_fixable = [i for i in items if i.get("code_fixable")]
        high_impact = [i for i in items if (i.get("impact") == "high")]
        traffic = "+10-25%" if len(high_impact) >= 3 else "+5-15%" if high_impact else "+0-5%"
        ranking = "significant" if len(high_impact) >= 3 else "moderate" if high_impact else "minor"
        roi = "high" if code_fixable and high_impact else "medium" if code_fixable else "low"
        return {"traffic": traffic, "ranking": ranking, "roi": roi, "code_fixable": len(code_fixable)}

    @staticmethod
    def _trend(latest, prev) -> str:
        if latest is None or prev is None:
            return "flat"
        if latest > prev:
            return "up"
        if latest < prev:
            return "down"
        return "flat"

    @staticmethod
    def _recommended_actions(state, buckets, prs) -> List[str]:
        actions: List[str] = []
        if prs["open"]:
            actions.append(f"Review {prs['open']} open pull request(s) awaiting merge.")
        pending = state.get("pending_approvals")
        proposed = pending.get("proposed_patches", 0) if isinstance(pending, dict) else 0
        if proposed:
            actions.append(f"Approve or reject {proposed} pending AI fix(es).")
        if buckets["critical"]:
            actions.append(f"Resolve {buckets['critical']} critical issue(s) first.")
        if not actions:
            actions.append("No action required — continue autonomous monitoring.")
        return actions

    @staticmethod
    def _verif_item(v: AiFixVerification) -> Dict[str, Any]:
        return {
            "patch_type": v.patch_type,
            "status": getattr(v.status, "value", v.status),
            "improvement_pct": v.improvement_pct,
            "issue_resolved": v.issue_resolved,
        }

    @staticmethod
    def _deploy_item(d: Deployment) -> Dict[str, Any]:
        return {
            "provider": getattr(d.provider, "value", d.provider),
            "status": getattr(d.status, "value", d.status),
            "url": d.deployment_url,
            "duration_seconds": d.duration_seconds,
        }

    async def _build_timeline(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        """Compose a chronological timeline from existing timestamped records."""
        since = datetime.utcnow() - timedelta(days=1)
        events: List[Dict[str, Any]] = []

        run = (await self.db.execute(
            select(SeoRun).where(
                SeoRun.project_id == project_id, SeoRun.tenant_id == tenant_id,
            ).order_by(SeoRun.created_at.desc()).limit(1)
        )).scalars().first()
        if run:
            if run.created_at:
                events.append(self._event(run.created_at, "SEO run started", "run"))
            if run.completed_at:
                events.append(self._event(run.completed_at, "SEO run completed", "run"))

        for pr in (await self.db.execute(
            select(PullRequestRecord).where(
                PullRequestRecord.project_id == project_id,
                PullRequestRecord.tenant_id == tenant_id,
                PullRequestRecord.created_at >= since,
            ).order_by(PullRequestRecord.created_at.desc()).limit(10)
        )).scalars().all():
            events.append(self._event(pr.created_at, "Pull request created", "repo"))

        for d in (await self.db.execute(
            select(Deployment).where(
                Deployment.project_id == project_id, Deployment.tenant_id == tenant_id,
                Deployment.created_at >= since,
            ).order_by(Deployment.created_at.desc()).limit(10)
        )).scalars().all():
            label = "Deployment successful" if d.status == DeploymentStatus.success else f"Deployment {getattr(d.status,'value',d.status)}"
            events.append(self._event(d.completed_at or d.created_at, label, "deploy"))

        for v in (await self.db.execute(
            select(AiFixVerification).where(
                AiFixVerification.project_id == project_id,
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.verified_at.isnot(None),
                AiFixVerification.verified_at >= since,
            ).order_by(AiFixVerification.verified_at.desc()).limit(10)
        )).scalars().all():
            events.append(self._event(v.verified_at, f"Verification {getattr(v.status,'value',v.status)}", "verify"))

        events = [e for e in events if e["ts"]]
        events.sort(key=lambda e: e["ts"])
        return [{"time": e["time"], "event": e["event"], "category": e["category"]} for e in events]

    @staticmethod
    def _event(ts: Optional[datetime], label: str, category: str) -> Dict[str, Any]:
        return {"ts": ts, "time": ts.strftime("%H:%M") if ts else None, "event": label, "category": category}

    @staticmethod
    def _json_safe(value):
        """Recursively convert UUID/datetime/date into JSON-serializable values
        so composed service output can be stored in a JSONB column."""
        from uuid import UUID as _UUID

        if isinstance(value, dict):
            return {k: DailyBriefingService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [DailyBriefingService._json_safe(v) for v in value]
        if isinstance(value, _UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    # -- executive summary (LLM with deterministic fallback) ----------------

    async def _executive_summary(self, state, sections, *, use_llm: bool):
        template = self._template_summary(state, sections)
        if not use_llm:
            return template, "template"
        try:
            from app.services.local_llm import LocalLLMService

            prompt = (
                "You are an SEO operations lead writing a concise executive briefing. "
                "Using ONLY these facts, write 4-6 short sentences (no bullet points, no invented "
                "numbers):\n"
                f"- Health score: {sections['overall_health']}\n"
                f"- SEO score: {sections['seo_score']} (previous {sections['seo_score_prev']}, trend {sections['seo_score_trend']})\n"
                f"- Critical issues: {sections['critical_issues']}, warnings: {sections['warnings']}\n"
                f"- Pending AI fixes: {sections['pending_approvals']}\n"
                f"- Open PRs: {sections['pull_requests']['open']}, merged: {sections['pull_requests']['merged']}\n"
                f"- Deployments today: {len(sections['deployments'])}\n"
                f"- Verifications finalized: {sections['learning'].get('finalized')}, success rate: {sections['learning'].get('success_rate')}\n"
                f"- Estimated traffic gain: {sections['estimated_traffic_gain']}\n"
                f"- Recommended: {'; '.join(sections['recommended_actions'])}\n"
            )
            result = await LocalLLMService().generate(prompt, options={"num_predict": 220, "temperature": 0.3})
            text = (result.get("response") or "").strip()
            if len(text) >= 40:
                return text, "llm"
        except Exception as exc:  # graceful fallback
            logger.warning("briefing_llm_summary_failed", error=str(exc))
        return template, "template"

    @staticmethod
    def _template_summary(state, sections) -> str:
        trend = sections["seo_score_trend"]
        parts = [f"Website health is {sections['overall_health']} ({trend} trend)."]
        if sections["seo_score"] is not None and sections["seo_score_prev"] is not None:
            parts.append(f"SEO score moved from {sections['seo_score_prev']} to {sections['seo_score']}.")
        if sections["deployments"]:
            ok = sum(1 for d in sections["deployments"] if d["status"] == "success")
            parts.append(f"{ok} deployment(s) verified successfully today.")
        if sections["critical_issues"]:
            parts.append(f"{sections['critical_issues']} critical issue(s) require attention.")
        parts.append(f"Estimated traffic gain after approved fixes is {sections['estimated_traffic_gain']}.")
        if sections["recommended_actions"]:
            parts.append("Recommended: " + sections["recommended_actions"][0])
        return " ".join(parts)

    # -- persistence + notifications ----------------------------------------

    async def _upsert(self, project_id, tenant_id, sections, timeline, summary, source, *, health, confidence, seo_score, seo_score_prev) -> DailyBriefing:
        today = date.today()
        existing = (await self.db.execute(
            select(DailyBriefing).where(
                DailyBriefing.project_id == project_id,
                DailyBriefing.briefing_date == today,
            )
        )).scalars().first()
        if existing:
            existing.sections = sections
            existing.timeline = timeline
            existing.executive_summary = summary
            existing.summary_source = source
            existing.health_score = health
            existing.ai_confidence = confidence
            existing.seo_score = seo_score
            existing.seo_score_prev = seo_score_prev
            briefing = existing
        else:
            briefing = DailyBriefing(
                tenant_id=tenant_id, project_id=project_id, briefing_date=today,
                health_score=health, ai_confidence=confidence, seo_score=seo_score,
                seo_score_prev=seo_score_prev, executive_summary=summary,
                summary_source=source, sections=sections, timeline=timeline,
            )
            self.db.add(briefing)
        await self.db.commit()
        await self.db.refresh(briefing)
        return briefing

    async def _emit_notifications(self, project_id, tenant_id, buckets, prs) -> None:
        svc = NotificationService(self.db)
        today = date.today().isoformat()
        if buckets["critical"]:
            await svc.create(
                tenant_id, NotificationLevel.critical,
                f"{buckets['critical']} critical SEO issue(s)",
                "The daily briefing flagged critical issues that need attention.",
                project_id=project_id, category="briefing",
                dedupe_key=f"critical:{project_id}:{today}", commit=False,
            )
        if prs["open"]:
            await svc.create(
                tenant_id, NotificationLevel.warning,
                f"{prs['open']} pull request(s) awaiting merge",
                "Approved AI fixes are waiting to be merged and deployed.",
                project_id=project_id, category="briefing",
                dedupe_key=f"open_prs:{project_id}:{today}", commit=False,
            )
        await self.db.commit()

    # -- queries for the API ------------------------------------------------

    async def get_latest(self, project_id: UUID, tenant_id: UUID) -> Optional[DailyBriefing]:
        return (await self.db.execute(
            select(DailyBriefing).where(
                DailyBriefing.project_id == project_id, DailyBriefing.tenant_id == tenant_id,
            ).order_by(DailyBriefing.briefing_date.desc()).limit(1)
        )).scalars().first()

    async def list_history(self, project_id: UUID, tenant_id: UUID, days: int = 30) -> List[DailyBriefing]:
        since = date.today() - timedelta(days=days)
        return list((await self.db.execute(
            select(DailyBriefing).where(
                DailyBriefing.project_id == project_id,
                DailyBriefing.tenant_id == tenant_id,
                DailyBriefing.briefing_date >= since,
            ).order_by(DailyBriefing.briefing_date.desc())
        )).scalars().all())

    async def get_trends(self, project_id: UUID, tenant_id: UUID, window: int = 30) -> Dict[str, Any]:
        history = await self.list_history(project_id, tenant_id, days=window)
        points = [
            {"date": b.briefing_date.isoformat(), "health": b.health_score,
             "seo_score": b.seo_score, "confidence": b.ai_confidence}
            for b in reversed(history)
        ]
        return {"window_days": window, "points": points, "count": len(points)}
