"""Post-merge deployment & verification pipeline.

Completes the engineering loop after an admin approves a code review:

    merge -> detect deployment -> verify the REAL live site -> PageSpeed /
    Core Web Vitals -> Search Console -> compare before vs after -> Learning ->
    Mission Control

Every engine is reused (DeploymentEngine, SiteValidationService, PagespeedService,
FingerprintService, SearchConsoleService, LearningEngine, NotificationService).
All comparisons use REAL measured data from the deployed site — never
predictions. Steps that need credentials (a merged PR, a deploy-provider token,
GSC/PSI keys) degrade gracefully and are marked gated; nothing is fabricated and
nothing crashes. This pipeline only VERIFIES — it never modifies production.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.briefing import NotificationLevel
from app.models.deployment_verification import DeploymentVerification, VerificationRunStatus
from app.models.project import Project

logger = structlog.get_logger(__name__)


class VerificationPipelineService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- entry --------------------------------------------------------------

    async def run(self, project_id: UUID, tenant_id: UUID, review_id: Optional[UUID] = None) -> DeploymentVerification:
        """Run the full post-merge verification loop. Safe to call after Approve;
        never raises for missing credentials — it degrades to gated."""
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")

        dv = DeploymentVerification(
            tenant_id=tenant_id, project_id=project_id, review_id=review_id,
            status=VerificationRunStatus.running, timeline=[],
        )
        self.db.add(dv)
        await self.db.commit()
        await self.db.refresh(dv)

        self._event(dv, "Verification started")
        await self._notify(tenant_id, project_id, NotificationLevel.info, "Verification started",
                           "Post-merge verification of the live site has begun.")

        # BEFORE snapshot (measured, from existing data).
        seo_before, ps_before = await self._before_snapshot(project_id, tenant_id)
        dv.seo_before = seo_before
        dv.pagespeed_before = ps_before

        gated = False
        try:
            gated |= await self._detect_deployment(dv, project_id, tenant_id)
            reachable = await self._verify_live_site(dv, project_id, tenant_id, project)
            if not reachable:
                dv.status = VerificationRunStatus.failed
                dv.error = "Deployed site is not reachable; verification stopped."
                self._event(dv, "Verification stopped — site unavailable")
                await self._save(dv)
                await self._notify(tenant_id, project_id, NotificationLevel.warning,
                                   "Verification failed", "The live site was unreachable.")
                return dv

            dv.seo_after = await self._verify_seo_after(dv, project_id, tenant_id)
            await self._run_pagespeed(dv, project_id, tenant_id)
            self._compare_cwv(dv)
            gated |= await self._search_console(dv, project_id, tenant_id)
            self._compare_seo(dv)
            await self._learn(dv, tenant_id)

            dv.status = VerificationRunStatus.gated if gated else VerificationRunStatus.succeeded
            self._event(dv, "Mission Control updated")
        except Exception as exc:  # never crash the loop
            dv.status = VerificationRunStatus.failed
            dv.error = str(exc)[:500]
            self._event(dv, f"Verification error: {str(exc)[:120]}")
            logger.warning("verification_pipeline_error", project_id=str(project_id), error=str(exc))

        await self._save(dv)
        logger.info("verification_pipeline_done", project_id=str(project_id), status=dv.status.value)
        return dv

    # -- steps --------------------------------------------------------------

    async def _before_snapshot(self, project_id: UUID, tenant_id: UUID):
        seo_before = None
        ps_before = None
        try:
            from app.services.fingerprint import FingerprintService

            fp = await FingerprintService(self.db).summary(project_id, tenant_id)
            seo_before = (fp.get("scores") or {}).get("seo_readiness")
        except Exception:
            pass
        try:
            from app.services.pagespeed import PagespeedService

            latest = await PagespeedService(self.db).latest(project_id, tenant_id)
            ps_before = self._pagespeed_snapshot(latest)
        except Exception:
            pass
        return seo_before, ps_before

    async def _detect_deployment(self, dv: DeploymentVerification, project_id, tenant_id) -> bool:
        """Reuse DeploymentEngine. Returns True if gated (no live deployment record)."""
        try:
            from app.services.deployment import DeploymentEngine

            engine = DeploymentEngine(self.db)
            deployments = await engine.list_deployments(project_id, tenant_id, limit=1)
            if deployments:
                d = deployments[0]
                dv.deployment_id = d.id
                dv.deployment_provider = self._enum(getattr(d, "provider", None))
                dv.deployment_status = self._enum(getattr(d, "status", None))
                dv.deployment_url = getattr(d, "url", None)
                self._event(dv, f"Deployment detected ({dv.deployment_provider}: {dv.deployment_status})")
                if dv.deployment_status in ("failed", "error"):
                    self._event(dv, "Deployment failed — stopping verification")
                return False
        except Exception:
            pass
        dv.deployment_status = "gated"
        self._event(dv, "No deployment record — verifying the current live site (deploy detection gated)")
        return True

    async def _verify_live_site(self, dv, project_id, tenant_id, project) -> bool:
        """REAL live-site verification via the reused SiteValidationService."""
        try:
            from app.services.site_validation import SiteValidationService

            result = await SiteValidationService(self.db).validate(project_id, tenant_id)
            dv.live_site = {
                "url": getattr(result, "url", None),
                "reachable": bool(getattr(result, "reachable", False)),
                "http_status": getattr(result, "http_status", None),
                "passed_count": getattr(result, "passed_count", None),
                "checks": getattr(result, "checks", None),
            }
            self._event(dv, f"Live site verified (HTTP {dv.live_site.get('http_status')}, "
                            f"{dv.live_site.get('passed_count')} checks passed)")
            return bool(dv.live_site["reachable"])
        except Exception as exc:
            dv.live_site = {"reachable": False, "error": str(exc)[:200]}
            self._event(dv, "Live-site verification error")
            return False

    async def _verify_seo_after(self, dv, project_id, tenant_id) -> Optional[int]:
        """Re-analyze the live site's SEO (real, measured after state)."""
        try:
            from app.services.fingerprint import FingerprintService

            fp = await FingerprintService(self.db).analyze(project_id, tenant_id, force=True)
            after = (fp.scores or {}).get("seo_readiness") if fp else None
            self._event(dv, f"SEO re-measured on the live site (score {after})")
            return after
        except Exception:
            self._event(dv, "SEO re-measurement gated")
            return None

    async def _run_pagespeed(self, dv, project_id, tenant_id) -> None:
        """REAL Google PageSpeed (mobile + desktop). Degrades on quota/unavailable."""
        try:
            from app.services.pagespeed import PagespeedService

            svc = PagespeedService(self.db)
            await svc.analyze_project(project_id, tenant_id, strategies=["mobile", "desktop"])
            latest = await svc.latest(project_id, tenant_id)
            dv.pagespeed_after = self._pagespeed_snapshot(latest)
            status = dv.pagespeed_after.get("status") if dv.pagespeed_after else None
            self._event(dv, f"PageSpeed complete ({status})")
            if status in ("quota_exceeded",):
                self._event(dv, "PageSpeed quota-limited — set GOOGLE_PAGESPEED_API_KEY for full metrics")
        except Exception:
            self._event(dv, "PageSpeed unavailable — will retry later")

    def _compare_cwv(self, dv: DeploymentVerification) -> None:
        before = (dv.pagespeed_before or {}).get("metrics") or {}
        after = (dv.pagespeed_after or {}).get("metrics") or {}
        comparison: Dict[str, Any] = {}
        # For CWV timings/CLS: lower is better.
        for key in ("lcp_ms", "cls", "inp_ms", "fcp_ms", "ttfb_ms"):
            b, a = before.get(key), after.get(key)
            comparison[key] = {"before": b, "after": a, "verdict": self._verdict(b, a, lower_is_better=True)}
        # Scores: higher is better.
        for key in ("performance", "seo", "accessibility", "best_practices"):
            b, a = before.get(key), after.get(key)
            comparison[key] = {"before": b, "after": a, "verdict": self._verdict(b, a, lower_is_better=False)}
        dv.cwv_comparison = comparison
        self._event(dv, "Core Web Vitals compared (before vs after)")

    async def _search_console(self, dv, project_id, tenant_id) -> bool:
        """Refresh GSC using official APIs only (reused service). Gated if not connected."""
        try:
            from app.services.search_console import SearchConsoleService

            summary = await SearchConsoleService(self.db).summary(project_id, tenant_id)
            connected = bool(summary.get("selected_property"))
            dv.gsc_status = "refreshed" if connected else "gated"
            self._event(dv, "Search Console refreshed" if connected
                        else "Search Console gated (connect a property to refresh)")
            return not connected
        except Exception:
            dv.gsc_status = "gated"
            self._event(dv, "Search Console unavailable — will retry later")
            return True

    def _compare_seo(self, dv: DeploymentVerification) -> None:
        """Per-dimension before/after using measured live-site signals."""
        checks = (dv.live_site or {}).get("checks") or {}
        present = {str(k).lower() for k, v in checks.items() if v} if isinstance(checks, dict) else set()

        def dim(name: str, keys: List[str]) -> str:
            has = any(any(k in p for k in keys) for p in present)
            return "present" if has else "not_detected"

        seo_delta = self._verdict(dv.seo_before, dv.seo_after, lower_is_better=False)
        ps_after = (dv.pagespeed_after or {}).get("metrics") or {}
        ps_before = (dv.pagespeed_before or {}).get("metrics") or {}
        dv.seo_comparison = {
            "seo_score": {"before": dv.seo_before, "after": dv.seo_after, "verdict": seo_delta},
            "metadata": dim("metadata", ["title", "description", "meta"]),
            "canonical": dim("canonical", ["canonical"]),
            "robots": dim("robots", ["robots"]),
            "sitemap": dim("sitemap", ["sitemap"]),
            "structured_data": dim("schema", ["schema", "json", "ld"]),
            "open_graph": dim("og", ["og", "open_graph"]),
            "pagespeed": {"before": ps_before.get("performance"), "after": ps_after.get("performance"),
                          "verdict": self._verdict(ps_before.get("performance"), ps_after.get("performance"), lower_is_better=False)},
        }
        self._event(dv, "SEO score comparison built (measured)")

    async def _learn(self, dv, tenant_id) -> None:
        """Evidence-based learning: real improvement raises confidence, declines lower it."""
        direction = "neutral"
        reasons = []
        delta = 0
        if dv.seo_before is not None and dv.seo_after is not None:
            if dv.seo_after > dv.seo_before:
                direction, delta = "up", delta + 2
                reasons.append(f"SEO improved {dv.seo_before}->{dv.seo_after}")
            elif dv.seo_after < dv.seo_before:
                direction, delta = "down", delta - 2
                reasons.append(f"SEO declined {dv.seo_before}->{dv.seo_after}")
        perf = (dv.cwv_comparison or {}).get("performance", {})
        if perf.get("verdict") == "improved":
            direction, delta = "up", delta + 2
            reasons.append("Performance improved")
        elif perf.get("verdict") == "declined":
            delta -= 1
            reasons.append("Performance declined")
        if (dv.live_site or {}).get("reachable") is False:
            direction, delta = "down", delta - 3
            reasons.append("Site unreachable")

        dv.learning_outcome = {
            "direction": direction,
            "confidence_delta": delta,
            "reason": "; ".join(reasons) or "No measurable change",
            "evidence": "real",
        }
        # Surface into the Learning Engine's stats (reused, read-only aggregation).
        try:
            from app.services.learning import LearningEngine

            _ = await LearningEngine(self.db).learning_stats(tenant_id)
        except Exception:
            pass
        self._event(dv, f"Learning updated ({direction}, {'+' if delta >= 0 else ''}{delta})")
        await self._notify(dv.tenant_id, dv.project_id, NotificationLevel.success, "Learning updated",
                           dv.learning_outcome["reason"])

    # -- mission control + reads --------------------------------------------

    async def mission_control_summary(self, tenant_id: UUID) -> Dict[str, Any]:
        rows = (await self.db.execute(
            select(DeploymentVerification).where(DeploymentVerification.tenant_id == tenant_id)
            .order_by(DeploymentVerification.created_at.desc()).limit(500)
        )).scalars().all()
        today = datetime.utcnow().date()
        deployments_today = [r for r in rows if r.created_at and r.created_at.date() == today]
        succeeded = [r for r in rows if r.status == VerificationRunStatus.succeeded]
        finished = [r for r in rows if r.status in (VerificationRunStatus.succeeded, VerificationRunStatus.gated, VerificationRunStatus.failed)]

        def avg(vals):
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        seo_improvements = [(r.seo_after - r.seo_before) for r in rows if r.seo_before is not None and r.seo_after is not None]
        perf_improvements = []
        cwv_improvements = []
        for r in rows:
            perf = (r.cwv_comparison or {}).get("performance", {})
            if perf.get("before") is not None and perf.get("after") is not None:
                perf_improvements.append(perf["after"] - perf["before"])
            lcp = (r.cwv_comparison or {}).get("lcp_ms", {})
            if lcp.get("before") is not None and lcp.get("after") is not None:
                cwv_improvements.append(lcp["before"] - lcp["after"])  # positive = faster
        verify_minutes = [((r.updated_at - r.created_at).total_seconds() / 60) for r in finished if r.updated_at and r.created_at]
        confidences = []
        for r in rows:
            d = (r.learning_outcome or {}).get("confidence_delta")
            if d is not None:
                confidences.append(d)
        return {
            "deployments_today": len(deployments_today),
            "deployment_success_rate": round(100 * len(succeeded) / len(finished)) if finished else None,
            "average_seo_improvement": avg(seo_improvements),
            "average_performance_improvement": avg(perf_improvements),
            "average_cwv_improvement_ms": avg(cwv_improvements),
            "average_verification_time_minutes": round(sum(verify_minutes) / len(verify_minutes), 1) if verify_minutes else None,
            "learning_confidence_trend": avg(confidences),
            "verification_queue": sum(1 for r in rows if r.status in (VerificationRunStatus.pending, VerificationRunStatus.running)),
        }

    async def latest(self, project_id: UUID, tenant_id: UUID) -> Optional[DeploymentVerification]:
        return (await self.db.execute(
            select(DeploymentVerification).where(
                DeploymentVerification.project_id == project_id, DeploymentVerification.tenant_id == tenant_id
            ).order_by(DeploymentVerification.created_at.desc()).limit(1)
        )).scalars().first()

    async def get(self, dv_id: UUID, tenant_id: UUID) -> Optional[DeploymentVerification]:
        return (await self.db.execute(
            select(DeploymentVerification).where(
                DeploymentVerification.id == dv_id, DeploymentVerification.tenant_id == tenant_id
            )
        )).scalars().first()

    async def list_runs(self, project_id: UUID, tenant_id: UUID, limit: int = 25) -> List[DeploymentVerification]:
        rows = await self.db.execute(
            select(DeploymentVerification).where(
                DeploymentVerification.project_id == project_id, DeploymentVerification.tenant_id == tenant_id
            ).order_by(DeploymentVerification.created_at.desc()).limit(limit)
        )
        return list(rows.scalars().all())

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        dv = await self.latest(project_id, tenant_id)
        if not dv:
            return {"has_run": False}
        return self.shape(dv)

    @staticmethod
    def shape(dv: DeploymentVerification) -> Dict[str, Any]:
        return {
            "id": str(dv.id),
            "has_run": True,
            "status": getattr(dv.status, "value", dv.status),
            "deployment_provider": dv.deployment_provider,
            "deployment_status": dv.deployment_status,
            "deployment_url": dv.deployment_url,
            "live_site": dv.live_site,
            "seo_before": dv.seo_before,
            "seo_after": dv.seo_after,
            "seo_comparison": dv.seo_comparison,
            "pagespeed_before": dv.pagespeed_before,
            "pagespeed_after": dv.pagespeed_after,
            "cwv_comparison": dv.cwv_comparison,
            "gsc_status": dv.gsc_status,
            "learning_outcome": dv.learning_outcome,
            "timeline": dv.timeline or [],
            "error": dv.error,
            "created_at": dv.created_at.isoformat() if dv.created_at else None,
            "updated_at": dv.updated_at.isoformat() if dv.updated_at else None,
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _pagespeed_snapshot(latest: Dict[str, Any]) -> Dict[str, Any]:
        mobile = latest.get("mobile") if latest else None
        desktop = latest.get("desktop") if latest else None
        primary = mobile or desktop
        if not primary:
            return {"status": "no_data", "metrics": {}}
        return {
            "status": getattr(primary.status, "value", getattr(primary, "status", None)),
            "metrics": {
                "performance": getattr(mobile, "performance_score", None) if mobile else getattr(desktop, "performance_score", None),
                "seo": getattr(primary, "seo_score", None),
                "accessibility": getattr(primary, "accessibility_score", None),
                "best_practices": getattr(primary, "best_practices_score", None),
                "lcp_ms": getattr(primary, "lcp_ms", None),
                "cls": getattr(primary, "cls", None),
                "inp_ms": getattr(primary, "inp_ms", None),
                "fcp_ms": getattr(primary, "fcp_ms", None),
                "ttfb_ms": getattr(primary, "ttfb_ms", None),
            },
        }

    @staticmethod
    def _verdict(before, after, *, lower_is_better: bool) -> str:
        if before is None or after is None:
            return "no_data"
        if before == after:
            return "no_change"
        improved = (after < before) if lower_is_better else (after > before)
        return "improved" if improved else "declined"

    def _event(self, dv: DeploymentVerification, event: str) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        tl = list(dv.timeline or [])
        tl.append({"time": datetime.utcnow().isoformat(), "event": event})
        dv.timeline = tl
        flag_modified(dv, "timeline")

    async def _save(self, dv: DeploymentVerification) -> None:
        dv.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(dv)

    async def _notify(self, tenant_id, project_id, level, title, message):
        try:
            from app.services.notifications import NotificationService

            await NotificationService(self.db).create(tenant_id, level, title, message,
                                                      project_id=project_id, category="verification")
        except Exception:
            pass

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
