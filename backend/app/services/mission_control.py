"""Enterprise Mission Control overview service.

Pure composition: one tenant-wide snapshot built entirely from existing services
and tables (SEO Brain, Learning, Verification, Deployment, Daily Briefing,
notifications) plus live infrastructure health. No SEO/business logic is
re-implemented here.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.qdrant import get_qdrant_status
from app.core.redis import get_redis_status
from app.models.audit import SEOAuditRun
from app.models.briefing import Notification
from app.models.deployment import Deployment, DeploymentStatus
from app.models.project import Project
from app.models.repo_agent import PullRequestRecord, PullRequestStatus, SeoCodePatch, SeoCodePatchStatus
from app.models.seo_run import SeoRun, SeoRunStatus
from app.models.verification import AiFixVerification, VerificationStatus
from app.services.daily_briefing import DailyBriefingService
from app.services.learning import LearningEngine
from app.services.notifications import NotificationService
from app.services.telemetry_query import TelemetryQuery
from app.services.stage_telemetry import StageTelemetryQuery

logger = structlog.get_logger(__name__)


class MissionControlService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def overview(self, tenant_id: UUID) -> Dict[str, Any]:
        projects = (await self.db.execute(
            select(Project).where(Project.tenant_id == tenant_id).order_by(Project.created_at.asc())
        )).scalars().all()

        system_health = await self._system_health()
        project_cards = [await self._project_card(p) for p in projects]
        current_activity = await self._current_activity(tenant_id, projects)
        pending = await self._pending_summary(tenant_id)
        learning = await LearningEngine(self.db).learning_stats(tenant_id)
        verification = await self._verification_summary(tenant_id)
        deployment = await self._deployment_summary(tenant_id)
        site_validation = await self._site_validation(tenant_id, projects)
        notifications = await self._notifications(tenant_id)
        recommendations = await self._recommendations(tenant_id, projects, current_activity)
        timeline = await self._timeline(tenant_id, projects, current_activity)

        search_console = await self._search_console_block(tenant_id, projects)
        technology = await self._technology_block(tenant_id, projects)
        generated_patches = await self._generated_patches_block(tenant_id, projects)

        tq = TelemetryQuery(self.db)
        telemetry_stats = await tq.stats(tenant_id)
        telemetry = {
            "stats": telemetry_stats,
            "workers": await tq.worker_health(tenant_id),
            "active": [self._job_item(j) for j in await tq.active_runs(tenant_id)],
            "recent": [self._job_item(j) for j in await tq.list_runs(tenant_id, limit=15)],
            "failures": [self._job_item(j) for j in await tq.failures(tenant_id, limit=10)],
        }

        # Per-stage pipeline visualisation (latest run of the most-active project)
        # + per-stage analytics across all runs.
        sq = StageTelemetryQuery(self.db)
        # Prefer an actively-running project's pipeline; otherwise show the most
        # recent run across the tenant (so the panel persists after completion).
        active_project = UUID(current_activity["project_id"]) if current_activity.get("project_id") else None
        pipeline = await sq.latest_pipeline(tenant_id, project_id=active_project)
        stage_analytics = await sq.stage_analytics(tenant_id)

        # Core Web Vitals summary for the most-active / first project.
        from app.services.pagespeed import PagespeedService

        cwv_target = active_project or (projects[-1].id if projects else None)
        core_web_vitals = await PagespeedService(self.db).summary(cwv_target, tenant_id) if cwv_target else {"status": "no_data"}

        # Aggregate health across projects for the headline number.
        healths = [c["health"] for c in project_cards if c["health"] is not None]
        overall_health = round(sum(healths) / len(healths)) if healths else None
        ai_health = self._ai_health_score(system_health, telemetry_stats, verification, learning, overall_health)

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "overall_health": overall_health,
            "ai_health_score": ai_health,
            "ai_confidence": learning.get("success_rate"),
            "system_health": system_health,
            "telemetry": telemetry,
            "pipeline": pipeline,
            "stage_analytics": stage_analytics,
            "search_console": search_console,
            "technology": technology,
            "generated_patches": generated_patches,
            "core_web_vitals": core_web_vitals,
            "current_activity": current_activity,
            "projects": project_cards,
            "project_count": len(project_cards),
            "pending_approvals": pending,
            "recommendations": recommendations,
            "notifications": notifications,
            "learning": {
                "success_rate": learning.get("success_rate"),
                "average_improvement_pct": learning.get("average_improvement_pct"),
                "finalized": learning.get("finalized"),
                "best": learning.get("most_successful_fixes", [])[:3],
                "worst": learning.get("least_successful_fixes", [])[:3],
            },
            "verification": verification,
            "deployment": deployment,
            "site_validation": site_validation,
            "scheduler": self._scheduler_status(),
            "timeline": timeline,
        }

    # -- system + infrastructure health -------------------------------------

    async def _system_health(self) -> Dict[str, Any]:
        db_ok = True
        try:
            await self.db.execute(select(1))
        except Exception:
            db_ok = False

        redis = get_redis_status()
        qdrant = get_qdrant_status()
        ollama = {"available": False}
        try:
            from app.services.local_llm import LocalLLMService

            ollama = await LocalLLMService().health_check()
        except Exception as exc:  # graceful
            ollama = {"available": False, "error": str(exc)}

        components = {
            "database": {"status": "ok" if db_ok else "down"},
            "redis": {"status": "ok" if redis.get("available") else ("optional" if not redis.get("required") else "down"),
                      "available": bool(redis.get("available"))},
            "qdrant": {"status": "ok" if qdrant.get("available") else "degraded", "available": bool(qdrant.get("available"))},
            "ollama": {"status": "ok" if ollama.get("available") else "degraded", "available": bool(ollama.get("available"))},
            "backend": {"status": "ok"},
        }
        healthy = db_ok and (redis.get("available") or not redis.get("required"))
        return {
            "status": "healthy" if healthy else "degraded",
            "environment": settings.APP_ENV,
            "components": components,
        }

    # -- per-project card (efficient direct queries) ------------------------

    async def _project_card(self, project: Project) -> Dict[str, Any]:
        latest_run = (await self.db.execute(
            select(SeoRun).where(SeoRun.project_id == project.id)
            .order_by(SeoRun.created_at.desc()).limit(1)
        )).scalars().first()

        seo_score = None
        if latest_run and latest_run.status == SeoRunStatus.completed and latest_run.audit_id:
            audit = (await self.db.execute(
                select(SEOAuditRun).where(SEOAuditRun.id == latest_run.audit_id)
            )).scalars().first()
            seo_score = float(audit.site_score) if audit and audit.site_score is not None else None

        pending_fixes = int((await self.db.execute(
            select(func.count(SeoCodePatch.id)).where(
                SeoCodePatch.project_id == project.id,
                SeoCodePatch.status == SeoCodePatchStatus.proposed,
            )
        )).scalar() or 0)
        open_prs = int((await self.db.execute(
            select(func.count(PullRequestRecord.id)).where(
                PullRequestRecord.project_id == project.id,
                PullRequestRecord.status.in_([PullRequestStatus.open, PullRequestStatus.draft]),
            )
        )).scalar() or 0)
        last_deploy = (await self.db.execute(
            select(Deployment).where(Deployment.project_id == project.id)
            .order_by(Deployment.created_at.desc()).limit(1)
        )).scalars().first()
        last_verif = (await self.db.execute(
            select(AiFixVerification).where(AiFixVerification.project_id == project.id)
            .order_by(AiFixVerification.created_at.desc()).limit(1)
        )).scalars().first()

        return {
            "project_id": str(project.id),
            "name": project.name,
            "domain": project.domain,
            "seo_score": seo_score,
            "health": int(seo_score) if seo_score is not None else None,
            "run_status": self._enum(getattr(latest_run, "status", None)) if latest_run else "none",
            "last_run_at": latest_run.completed_at.isoformat() if latest_run and latest_run.completed_at else None,
            "pending_fixes": pending_fixes,
            "open_prs": open_prs,
            "last_deployment": self._enum(getattr(last_deploy, "status", None)) if last_deploy else None,
            "last_verification": self._enum(getattr(last_verif, "status", None)) if last_verif else None,
        }

    # -- current AI activity -------------------------------------------------

    async def _current_activity(self, tenant_id: UUID, projects) -> Dict[str, Any]:
        running = (await self.db.execute(
            select(SeoRun).where(
                SeoRun.tenant_id == tenant_id,
                SeoRun.status == SeoRunStatus.running,
            ).order_by(SeoRun.created_at.desc()).limit(1)
        )).scalars().first()
        if not running:
            return {"active": False, "task": "idle", "project_id": None}
        name = next((p.name for p in projects if p.id == running.project_id), None)
        stages = getattr(running, "stage_statuses", None) or {}
        done = sum(1 for v in stages.values() if v == "completed")
        total = len(stages) or 5
        return {
            "active": True,
            "task": "SEO analysis",
            "project_id": str(running.project_id),
            "project_name": name,
            "current_stage": self._enum(getattr(running, "current_stage", None)),
            "stage_statuses": stages,
            "progress_pct": round(done / total * 100),
        }

    # -- pending approvals ---------------------------------------------------

    async def _pending_summary(self, tenant_id: UUID) -> Dict[str, int]:
        proposed = int((await self.db.execute(
            select(func.count(SeoCodePatch.id)).where(
                SeoCodePatch.tenant_id == tenant_id, SeoCodePatch.status == SeoCodePatchStatus.proposed)
        )).scalar() or 0)
        open_prs = int((await self.db.execute(
            select(func.count(PullRequestRecord.id)).where(
                PullRequestRecord.tenant_id == tenant_id,
                PullRequestRecord.status.in_([PullRequestStatus.open, PullRequestStatus.draft]))
        )).scalar() or 0)
        verif_queue = int((await self.db.execute(
            select(func.count(AiFixVerification.id)).where(
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status.in_([VerificationStatus.pending, VerificationStatus.running]))
        )).scalar() or 0)
        needs_review = int((await self.db.execute(
            select(func.count(AiFixVerification.id)).where(
                AiFixVerification.tenant_id == tenant_id,
                AiFixVerification.status == VerificationStatus.needs_human_review)
        )).scalar() or 0)
        pending_deploys = int((await self.db.execute(
            select(func.count(Deployment.id)).where(
                Deployment.tenant_id == tenant_id,
                Deployment.status.in_(["pending", "building"]))
        )).scalar() or 0)
        unread = await NotificationService(self.db).unread_count(tenant_id)
        return {
            "pending_ai_fixes": proposed,
            "open_pull_requests": open_prs,
            "pending_verification": verif_queue,
            "pending_deployments": pending_deploys,
            "needs_human_review": needs_review,
            "unread_notifications": unread,
        }

    # -- recommendations (reuse the Brain master plan) ----------------------

    async def _recommendations(self, tenant_id: UUID, projects, current_activity) -> List[Dict[str, Any]]:
        target = None
        if current_activity.get("project_id"):
            target = UUID(current_activity["project_id"])
        elif projects:
            target = projects[-1].id  # most recently created
        if not target:
            return []
        from app.services.seo_brain import SeoBrainService

        try:
            plan = await SeoBrainService(self.db).get_master_plan(target, tenant_id, limit=10)
        except Exception:
            return []
        out = []
        for it in plan.get("items", [])[:10]:
            out.append({
                "title": it.get("title"),
                "reason": it.get("description") or it.get("recommended_fix"),
                "impact": it.get("impact"),
                "expected_traffic_gain": it.get("expected_traffic_gain"),
                "expected_ranking_gain": it.get("expected_ranking_gain"),
                "difficulty": it.get("difficulty"),
                "roi": it.get("business_impact"),
                "confidence": it.get("confidence"),
                "code_fixable": it.get("code_fixable"),
                "priority_score": it.get("priority_score"),
            })
        return out

    async def _verification_summary(self, tenant_id: UUID) -> Dict[str, Any]:
        rows = (await self.db.execute(
            select(AiFixVerification.status, func.count(AiFixVerification.id))
            .where(AiFixVerification.tenant_id == tenant_id)
            .group_by(AiFixVerification.status)
        )).all()
        counts = {self._enum(s): int(c) for s, c in rows}
        return {
            "verified_success": counts.get("verified_success", 0),
            "partially_successful": counts.get("partially_successful", 0),
            "failed": counts.get("failed", 0),
            "needs_human_review": counts.get("needs_human_review", 0),
            "pending": counts.get("pending", 0) + counts.get("running", 0),
        }

    async def _deployment_summary(self, tenant_id: UUID) -> Dict[str, Any]:
        from app.deployment.adapters import provider_health
        from app.services.deployment import DeploymentEngine

        recent = (await self.db.execute(
            select(Deployment).where(Deployment.tenant_id == tenant_id)
            .order_by(Deployment.created_at.desc()).limit(8)
        )).scalars().all()
        last_success = (await self.db.execute(
            select(Deployment).where(
                Deployment.tenant_id == tenant_id, Deployment.status == DeploymentStatus.success,
            ).order_by(Deployment.completed_at.desc().nullslast()).limit(1)
        )).scalars().first()
        active = [d for d in recent if self._enum(d.status) in ("pending", "building")]
        return {
            "recent": [
                {"provider": self._enum(d.provider), "status": self._enum(d.status),
                 "url": d.deployment_url, "duration_seconds": d.duration_seconds,
                 "created_at": d.created_at.isoformat() if d.created_at else None}
                for d in recent[:5]
            ],
            "active_count": len(active),
            "last_success_at": last_success.completed_at.isoformat() if last_success and last_success.completed_at else None,
            "stats": await DeploymentEngine(self.db).deployment_stats(tenant_id),
            "provider_health": provider_health(),
        }

    async def _site_validation(self, tenant_id: UUID, projects) -> Dict[str, Any]:
        """Most recent live-site validation across the tenant (any project)."""
        from app.models.site_validation import SiteValidation
        from app.services.site_validation import SiteValidationService

        latest = (await self.db.execute(
            select(SiteValidation).where(SiteValidation.tenant_id == tenant_id)
            .order_by(SiteValidation.created_at.desc()).limit(1)
        )).scalars().first()
        if not latest:
            return {"status": "no_data"}
        return await SiteValidationService(self.db).summary(latest.project_id, tenant_id)

    async def _notifications(self, tenant_id: UUID) -> Dict[str, Any]:
        svc = NotificationService(self.db)
        items = await svc.list(tenant_id, limit=20)
        return {
            "unread_count": await svc.unread_count(tenant_id),
            "items": [
                {"id": str(n.id), "level": self._enum(n.level), "category": n.category,
                 "title": n.title, "message": n.message, "read": n.read,
                 "created_at": n.created_at.isoformat() if n.created_at else None}
                for n in items
            ],
        }

    async def _timeline(self, tenant_id: UUID, projects, current_activity) -> List[Dict[str, Any]]:
        target = None
        if current_activity.get("project_id"):
            target = UUID(current_activity["project_id"])
        elif projects:
            target = projects[-1].id
        if not target:
            return []
        try:
            return await DailyBriefingService(self.db)._build_timeline(target, tenant_id)
        except Exception:
            return []

    async def _search_console_block(self, tenant_id: UUID, projects) -> Dict[str, Any]:
        """GSC connection status + Auto Index Queue summary (credential-gated;
        degrades gracefully when Search Console is not connected)."""
        from app.models.search_console import GSCConnection
        from app.services.index_queue import IndexQueueService

        connected = int((await self.db.execute(
            select(func.count(GSCConnection.id)).where(GSCConnection.tenant_id == tenant_id)
        )).scalar() or 0)

        index_queue = {"pending": 0, "approved": 0, "submitted": 0, "total": 0}
        if projects:
            try:
                index_queue = await IndexQueueService(self.db).summary(projects[-1].id, tenant_id)
            except Exception:
                pass
        return {
            "connected": connected > 0,
            "connections": connected,
            "index_queue": index_queue,
            "note": None if connected else "Connect Google Search Console to enable sitemap submission and indexing status.",
        }

    async def _technology_block(self, tenant_id: UUID, projects) -> Dict[str, Any]:
        """Technology Overview (business-friendly stack summary + readiness
        scores). Prefers a project that already has a completed fingerprint so
        Mission Control shows real detected technology; degrades gracefully to a
        not-analyzed shape otherwise."""
        from app.models.fingerprint import FingerprintStatus, TechnologyFingerprint
        from app.services.fingerprint import FingerprintService

        if not projects:
            return {"status": "not_analyzed", "detected": False, "scores": {}, "technologies": []}
        try:
            fp = (await self.db.execute(
                select(TechnologyFingerprint).where(
                    TechnologyFingerprint.tenant_id == tenant_id,
                    TechnologyFingerprint.status == FingerprintStatus.complete,
                ).order_by(TechnologyFingerprint.detected_at.desc()).limit(1)
            )).scalars().first()
            target = fp.project_id if fp else projects[-1].id
            return await FingerprintService(self.db).summary(target, tenant_id)
        except Exception:
            return {"status": "not_analyzed", "detected": False, "scores": {}, "technologies": []}

    async def _generated_patches_block(self, tenant_id: UUID, projects) -> Dict[str, Any]:
        """Generated SEO Patch section — framework, counts, ready-for-PR. Prefers
        a project that already has generated patches; degrades gracefully."""
        from app.models.generated_patch import GeneratedSeoPatch
        from app.services.framework_patch_generator import FrameworkPatchGeneratorService

        if not projects:
            return {"total": 0, "ready_for_pr": 0, "framework": None, "by_status": {}}
        try:
            row = (await self.db.execute(
                select(GeneratedSeoPatch.project_id).where(
                    GeneratedSeoPatch.tenant_id == tenant_id
                ).order_by(GeneratedSeoPatch.created_at.desc()).limit(1)
            )).scalar()
            target = row or projects[-1].id
            return await FrameworkPatchGeneratorService(self.db).summary(target, tenant_id)
        except Exception:
            return {"total": 0, "ready_for_pr": 0, "framework": None, "by_status": {}}

    def _scheduler_status(self) -> Dict[str, Any]:
        # The scheduler runs on a fixed interval; detailed per-job telemetry is a
        # follow-up. Surface the configured cadence honestly.
        return {
            "interval_seconds": settings.SCHEDULER_INTERVAL_SECONDS,
            "tick_limit": settings.SCHEDULER_TICK_LIMIT,
            "status": "configured",
        }

    @staticmethod
    def _job_item(j) -> Dict[str, Any]:
        return {
            "id": str(j.id),
            "job_name": j.job_name,
            "job_type": j.job_type,
            "status": MissionControlService._enum(j.status),
            "trigger_type": MissionControlService._enum(j.trigger_type),
            "worker_name": j.worker_name,
            "retry_count": j.retry_count,
            "duration_ms": j.duration_ms,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "error_message": j.error_message,
        }

    @staticmethod
    def _ai_health_score(system_health, telemetry_stats, verification, learning, overall_health) -> int:
        """One 0-100 AI health score blending infra, scheduler/workers, SEO
        pipeline and verification signals. Weights sum to 100; each sub-score is
        0-1 and degrades gracefully when a signal has no data yet."""
        comps = system_health.get("components", {})
        infra_total = len(comps) or 1
        infra_ok = sum(1 for c in comps.values() if c.get("status") == "ok")
        infra = infra_ok / infra_total

        fail_rate = telemetry_stats.get("failure_rate")
        workers = 1.0 if fail_rate is None else max(0.0, 1 - fail_rate / 100)

        pipeline = (overall_health / 100) if overall_health is not None else 0.7

        v_total = sum(v for v in verification.values() if isinstance(v, int))
        v_ok = verification.get("verified_success", 0) + 0.5 * verification.get("partially_successful", 0)
        verif = (v_ok / v_total) if v_total else 0.7  # neutral when no evidence

        learn_rate = learning.get("success_rate")
        learn = (learn_rate / 100) if learn_rate is not None else 0.7

        score = (infra * 30) + (workers * 25) + (pipeline * 20) + (verif * 15) + (learn * 10)
        return int(round(max(0, min(100, score))))

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
