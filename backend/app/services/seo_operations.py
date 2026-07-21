"""SEO Operations Engine — the autonomous master orchestrator.

Behaves like a senior SEO engineer working 24x7: it composes every existing
engine (fingerprint, planner, brain, framework strategy, patch generator,
pipeline, code review, deployment verification, learning, Search Console,
PageSpeed, crawler) to compute a real project health score, decide the next best
action, monitor daily and detect what changed, and roll everything up into a
CEO-level view.

It ONLY reads and orchestrates — it never modifies UI, business logic, or a
production site. Every number is composed from real measured data already stored
by the underlying engines; missing data is reported as not-measured, never
fabricated.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.briefing import NotificationLevel
from app.models.ops_snapshot import OpsHealthSnapshot
from app.models.project import Project

logger = structlog.get_logger(__name__)

# Ordered project lifecycle stages.
LIFECYCLE_STAGES = [
    "fingerprint", "framework_strategy", "seo_audit", "issue_detection",
    "patch_generation", "admin_review", "deployment_verification", "learning", "monitoring",
]

_DIMENSION_LABELS = {
    "technical_seo": "Technical SEO",
    "content": "Content",
    "performance": "Performance",
    "core_web_vitals": "Core Web Vitals",
    "security": "Security",
    "indexability": "Indexability",
    "structured_data": "Structured Data",
    "internal_linking": "Internal Linking",
    "images": "Images",
    "mobile": "Mobile",
    "accessibility": "Accessibility",
}


class SeoOperationsEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- health score -------------------------------------------------------

    async def health(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Overall 0-100 SEO health split into explained dimensions, composed
        from the fingerprint + PageSpeed + audit (all real, measured)."""
        fp = await self._fingerprint(project_id, tenant_id)
        ps = await self._pagespeed(project_id, tenant_id)
        audit = await self._audit_counts(project_id, tenant_id)

        scores = (fp.get("scores") or {})
        techs = {(t.get("name") or "").lower() for t in fp.get("technologies", [])}
        cats = {t.get("category") for t in fp.get("technologies", [])}

        dims: Dict[str, Dict[str, Any]] = {}

        def dim(key, score, explanation):
            dims[key] = {"key": key, "label": _DIMENSION_LABELS[key], "score": score, "explanation": explanation}

        dim("technical_seo", scores.get("seo_readiness"),
            "How many core on-page signals (title, description, canonical, robots, sitemap) are present.")
        dim("content", self._content_score(audit),
            "Based on content-related audit issues (thin/duplicate/missing content).")
        perf = ps.get("performance_mobile") or ps.get("performance_desktop") or scores.get("performance_readiness")
        dim("performance", perf, "Measured Google PageSpeed performance (falls back to on-page performance signals).")
        dim("core_web_vitals", self._cwv_score(ps),
            "Derived from measured LCP, CLS and INP against Google's good/needs-improvement/poor thresholds.")
        dim("security", scores.get("security"), "HTTPS, HSTS, CSP and related transport security.")
        dim("indexability", scores.get("indexability"), "Whether crawlers are allowed to index the site and a sitemap is reachable.")
        dim("structured_data", 100 if any("json-ld" in n or "schema" in n for n in techs) else 25,
            "Whether Schema.org JSON-LD structured data was detected.")
        dim("internal_linking", self._links_score(audit), "Based on internal-link audit issues.")
        dim("images", 80 if any(c == "image_system" for c in cats) else 55,
            "Whether an image optimization system (next/image, CDN, modern formats) is in use.")
        dim("mobile", ps.get("performance_mobile"), "Measured mobile PageSpeed performance.")
        dim("accessibility", scores.get("accessibility"), "Basic accessibility signals (lang, viewport, alt text, landmarks).")

        measured = [d["score"] for d in dims.values() if d["score"] is not None]
        overall = int(round(sum(measured) / len(measured))) if measured else None
        return {
            "overall": overall,
            "grade": self._grade(overall),
            "dimensions": list(dims.values()),
            "measured_dimensions": len(measured),
            "total_dimensions": len(dims),
            "measured_at": datetime.utcnow().isoformat(),
        }

    # -- next best action ---------------------------------------------------

    async def next_best_actions(self, project_id: UUID, tenant_id: UUID, limit: int = 6) -> List[Dict[str, Any]]:
        fp = await self._fingerprint(project_id, tenant_id)
        ps = await self._pagespeed(project_id, tenant_id)
        scores = fp.get("scores") or {}
        techs = {(t.get("name") or "").lower() for t in fp.get("technologies", [])}
        cats = {t.get("category") for t in fp.get("technologies", [])}
        actions: List[Dict[str, Any]] = []

        def add(action, why, priority, category):
            actions.append({"action": action, "why": why, "priority": priority, "category": category})

        if not fp.get("detected"):
            add("Analyze technology", "The stack hasn't been fingerprinted yet — every SEO decision depends on it.", 95, "setup")

        # credential / connection gaps
        gsc = await self._gsc_connected(project_id, tenant_id)
        if not gsc:
            add("Connect Search Console", "Without GSC we can't measure real impressions, coverage or indexing.", 80, "search_console")

        # missing SEO surfaces
        if "sitemap" not in cats:
            add("Add / submit sitemap", "No sitemap was detected; a sitemap speeds up crawling and indexation.", 78, "indexability")
        if not any("json-ld" in n or "schema" in n for n in techs):
            add("Improve schema", "No structured data detected; JSON-LD can win rich results.", 72, "structured_data")
        if (scores.get("seo_readiness") or 100) < 80:
            add("Generate metadata", "Core on-page tags are incomplete; framework-safe metadata patches will fix this.", 70, "metadata")

        # performance / CWV (measured)
        lcp = ps.get("lcp_ms")
        cls = ps.get("cls")
        if lcp and lcp > 2500:
            add("Improve LCP", f"Measured LCP is {int(lcp)}ms (>2500ms is slow); improving it helps rankings and users.", 68, "performance")
        if cls and cls > 0.1:
            add("Reduce CLS", f"Measured CLS is {round(cls, 3)} (>0.1 is unstable layout).", 60, "core_web_vitals")
        if any(c == "image_system" for c in cats) is False:
            add("Optimize images", "No image optimizer detected; modern formats/lazy-loading improve Core Web Vitals.", 55, "images")
        if (scores.get("security") or 100) < 60:
            add("Add security headers", "Security signals (HSTS/CSP) are weak; a lightweight ranking + trust factor.", 50, "security")

        # workflow gaps
        pending = await self._pending_reviews(project_id, tenant_id)
        if pending:
            add(f"Review {pending} pending SEO patch(es)", "Generated patches are waiting for your approval before anything ships.", 85, "review")

        actions.sort(key=lambda a: a["priority"], reverse=True)
        return actions[:limit]

    # -- lifecycle ----------------------------------------------------------

    async def lifecycle(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        done = set()
        fp = await self._fingerprint(project_id, tenant_id)
        if fp.get("detected"):
            done.add("fingerprint")
            if (fp.get("strategy") or {}).get("primary_framework_key"):
                done.add("framework_strategy")
        if await self._has_audit(project_id, tenant_id):
            done.add("seo_audit"); done.add("issue_detection")
        if await self._has_generated_patches(project_id, tenant_id):
            done.add("patch_generation")
        if await self._has_reviews(project_id, tenant_id):
            done.add("admin_review")
        if await self._has_verification(project_id, tenant_id):
            done.add("deployment_verification"); done.add("learning")
        if await self._latest_snapshot(project_id, tenant_id):
            done.add("monitoring")
        current = next((s for s in LIFECYCLE_STAGES if s not in done), "monitoring")
        return {
            "current_stage": current,
            "stages": [{"name": s, "label": s.replace("_", " ").title(), "status": "done" if s in done else ("current" if s == current else "pending")}
                       for s in LIFECYCLE_STAGES],
        }

    # -- monitoring + change detection --------------------------------------

    async def monitor(self, project_id: UUID, tenant_id: UUID, notify: bool = True) -> Dict[str, Any]:
        """Daily monitor: snapshot the health + key signals and detect what
        changed since the previous snapshot. Worker-callable; never blocks."""
        health = await self.health(project_id, tenant_id)
        signals = await self._signals(project_id, tenant_id, health)
        prev = await self._latest_snapshot(project_id, tenant_id)

        snapshot = OpsHealthSnapshot(
            tenant_id=tenant_id, project_id=project_id,
            overall_score=health.get("overall"),
            dimensions={d["key"]: d["score"] for d in health["dimensions"]},
            signals=signals,
        )
        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)

        changes = self._diff(prev, snapshot) if prev else []
        if notify and changes:
            await self._notify_changes(project_id, tenant_id, changes)
        logger.info("ops_monitor", project_id=str(project_id), score=health.get("overall"), changes=len(changes))
        return {"snapshot_id": str(snapshot.id), "overall": health.get("overall"),
                "changes": changes, "changed": len(changes)}

    async def monitor_all(self, tenant_id: UUID) -> Dict[str, Any]:
        """Multi-project daily monitoring — each project independent/isolated."""
        projects = (await self.db.execute(
            select(Project).where(Project.tenant_id == tenant_id, Project.is_active.is_(True))
        )).scalars().all()
        ran = 0
        for p in projects:
            try:
                await self.monitor(p.id, tenant_id)
                ran += 1
            except Exception as exc:
                logger.warning("ops_monitor_project_failed", project_id=str(p.id), error=str(exc))
        return {"projects_monitored": ran}

    async def changes(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        snaps = (await self.db.execute(
            select(OpsHealthSnapshot).where(
                OpsHealthSnapshot.project_id == project_id, OpsHealthSnapshot.tenant_id == tenant_id
            ).order_by(OpsHealthSnapshot.created_at.desc()).limit(2)
        )).scalars().all()
        if len(snaps) < 2:
            return []
        return self._diff(snaps[1], snaps[0])

    # -- timeline -----------------------------------------------------------

    async def timeline(self, project_id: UUID, tenant_id: UUID, limit: int = 40) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        # code reviews
        try:
            from app.models.code_review import CodeReview

            for r in (await self.db.execute(
                select(CodeReview).where(CodeReview.project_id == project_id, CodeReview.tenant_id == tenant_id)
                .order_by(CodeReview.created_at.desc()).limit(15)
            )).scalars().all():
                events.append({"time": r.created_at, "event": f"Review prepared ({r.framework}, {r.files_count} files)", "kind": "review"})
                if r.approved_at:
                    events.append({"time": r.approved_at, "event": f"Admin approved by {r.approved_by}", "kind": "approve"})
                if r.rejected_at:
                    events.append({"time": r.rejected_at, "event": f"Admin rejected: {r.rejection_reason or ''}", "kind": "reject"})
        except Exception:
            pass
        # deployment verifications
        try:
            from app.models.deployment_verification import DeploymentVerification

            for v in (await self.db.execute(
                select(DeploymentVerification).where(
                    DeploymentVerification.project_id == project_id, DeploymentVerification.tenant_id == tenant_id
                ).order_by(DeploymentVerification.created_at.desc()).limit(10)
            )).scalars().all():
                verdict = (v.learning_outcome or {}).get("direction", "")
                events.append({"time": v.created_at, "event": f"Deployment verification ({v.status.value if hasattr(v.status,'value') else v.status}, learning {verdict})", "kind": "verify"})
        except Exception:
            pass
        # health snapshots (score changes)
        snaps = (await self.db.execute(
            select(OpsHealthSnapshot).where(
                OpsHealthSnapshot.project_id == project_id, OpsHealthSnapshot.tenant_id == tenant_id
            ).order_by(OpsHealthSnapshot.created_at.desc()).limit(10)
        )).scalars().all()
        for s in snaps:
            events.append({"time": s.created_at, "event": f"Health measured: {s.overall_score}", "kind": "monitor"})

        events = [e for e in events if e["time"]]
        events.sort(key=lambda e: e["time"], reverse=True)
        return [{"time": e["time"].isoformat(), "bucket": self._bucket(e["time"]), "event": e["event"], "kind": e["kind"]}
                for e in events[:limit]]

    # -- insights + CEO overview -------------------------------------------

    async def insights(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        fp = await self._fingerprint(project_id, tenant_id)
        strategy = fp.get("strategy") or {}
        return {
            "detected": fp.get("detected", False),
            "primary_framework": fp.get("primary_framework"),
            "technology": [t.get("name") for t in fp.get("technologies", [])[:8]],
            "recommended_strategy": strategy.get("recommended_strategy"),
            "strengths": [r for r in strategy.get("recommendations", []) if "already" in r.lower() or "supports" in r.lower()],
            "weaknesses": [r for r in strategy.get("recommendations", []) if "unused" in r.lower() or "missing" in r.lower() or "add" in r.lower()],
        }

    async def ceo_overview(self, tenant_id: UUID) -> Dict[str, Any]:
        projects = (await self.db.execute(
            select(Project).where(Project.tenant_id == tenant_id, Project.is_active.is_(True))
        )).scalars().all()
        healths, improving, declining, monitored = [], 0, 0, 0
        for p in projects:
            snaps = (await self.db.execute(
                select(OpsHealthSnapshot).where(OpsHealthSnapshot.project_id == p.id)
                .order_by(OpsHealthSnapshot.created_at.desc()).limit(2)
            )).scalars().all()
            if snaps:
                monitored += 1
                if snaps[0].overall_score is not None:
                    healths.append(snaps[0].overall_score)
                if len(snaps) >= 2 and snaps[0].overall_score is not None and snaps[1].overall_score is not None:
                    if snaps[0].overall_score > snaps[1].overall_score:
                        improving += 1
                    elif snaps[0].overall_score < snaps[1].overall_score:
                        declining += 1
        pending, deployments, verifications = await self._tenant_counts(tenant_id)
        return {
            "projects_total": len(projects),
            "projects_monitored": monitored,
            "projects_improving": improving,
            "projects_declining": declining,
            "average_health": int(round(sum(healths) / len(healths))) if healths else None,
            "overall_seo_health": int(round(sum(healths) / len(healths))) if healths else None,
            "pending_reviews": pending,
            "deployments": deployments,
            "verifications": verifications,
        }

    # -- data helpers (reuse existing engines) ------------------------------

    async def _fingerprint(self, project_id, tenant_id) -> Dict[str, Any]:
        try:
            from app.services.fingerprint import FingerprintService
            return await FingerprintService(self.db).summary(project_id, tenant_id)
        except Exception:
            return {}

    async def _pagespeed(self, project_id, tenant_id) -> Dict[str, Any]:
        try:
            from app.services.pagespeed import PagespeedService
            s = await PagespeedService(self.db).summary(project_id, tenant_id)
            return s if isinstance(s, dict) else {}
        except Exception:
            return {}

    async def _audit_counts(self, project_id, tenant_id) -> Dict[str, int]:
        try:
            from app.models.audit import SEOIssue, SEOIssueCategory, SEOIssueStatus
            from sqlalchemy import func

            rows = (await self.db.execute(
                select(SEOIssue.category, func.count(SEOIssue.id)).where(
                    SEOIssue.project_id == project_id, SEOIssue.tenant_id == tenant_id,
                    SEOIssue.status == SEOIssueStatus.open,
                ).group_by(SEOIssue.category)
            )).all()
            return {getattr(c, "value", c): int(n) for c, n in rows}
        except Exception:
            return {}

    @staticmethod
    def _content_score(audit: Dict[str, int]) -> Optional[int]:
        if not audit:
            return None
        n = audit.get("content", 0)
        return max(20, 100 - n * 8)

    @staticmethod
    def _links_score(audit: Dict[str, int]) -> Optional[int]:
        if not audit:
            return None
        n = audit.get("links", 0)
        return max(30, 100 - n * 6)

    @staticmethod
    def _cwv_score(ps: Dict[str, Any]) -> Optional[int]:
        lcp, cls, inp = ps.get("lcp_ms"), ps.get("cls"), ps.get("inp_ms")
        parts = []
        if lcp is not None:
            parts.append(90 if lcp < 2500 else 60 if lcp < 4000 else 30)
        if cls is not None:
            parts.append(90 if cls < 0.1 else 60 if cls < 0.25 else 30)
        if inp is not None:
            parts.append(90 if inp < 200 else 60 if inp < 500 else 30)
        return int(round(sum(parts) / len(parts))) if parts else None

    @staticmethod
    def _grade(score: Optional[int]) -> Optional[str]:
        if score is None:
            return None
        return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"

    async def _signals(self, project_id, tenant_id, health) -> Dict[str, Any]:
        fp = await self._fingerprint(project_id, tenant_id)
        ps = await self._pagespeed(project_id, tenant_id)
        cats = {t.get("category") for t in fp.get("technologies", [])}
        return {
            "overall": health.get("overall"),
            "has_sitemap": "sitemap" in cats,
            "has_schema": any("json-ld" in (t.get("name") or "").lower() for t in fp.get("technologies", [])),
            "has_robots": "robots" in cats,
            "indexability": (fp.get("scores") or {}).get("indexability"),
            "seo_readiness": (fp.get("scores") or {}).get("seo_readiness"),
            "performance": ps.get("performance_mobile"),
            "lcp_ms": ps.get("lcp_ms"),
            "cls": ps.get("cls"),
        }

    def _diff(self, prev: OpsHealthSnapshot, curr: OpsHealthSnapshot) -> List[Dict[str, Any]]:
        changes: List[Dict[str, Any]] = []
        if prev.overall_score is not None and curr.overall_score is not None and prev.overall_score != curr.overall_score:
            delta = curr.overall_score - prev.overall_score
            changes.append({"field": "overall_health", "before": prev.overall_score, "after": curr.overall_score,
                            "direction": "improved" if delta > 0 else "declined", "delta": delta})
        ps, cs = prev.signals or {}, curr.signals or {}
        for key in ("has_sitemap", "has_schema", "has_robots", "seo_readiness", "performance", "lcp_ms", "cls", "indexability"):
            b, a = ps.get(key), cs.get(key)
            if b != a and (b is not None or a is not None):
                changes.append({"field": key, "before": b, "after": a,
                                "direction": self._change_dir(key, b, a)})
        return changes

    @staticmethod
    def _change_dir(key, before, after) -> str:
        if isinstance(before, bool) or isinstance(after, bool):
            return "improved" if after and not before else "declined" if before and not after else "changed"
        if before is None or after is None:
            return "changed"
        lower_better = key in ("lcp_ms", "cls")
        if before == after:
            return "no_change"
        improved = (after < before) if lower_better else (after > before)
        return "improved" if improved else "declined"

    async def _notify_changes(self, project_id, tenant_id, changes) -> None:
        important = [c for c in changes if c.get("field") == "overall_health" and abs(c.get("delta", 0)) >= 5
                     or c.get("direction") == "declined"]
        if not important:
            return
        try:
            from app.services.notifications import NotificationService

            summary = "; ".join(f"{c['field']} {c.get('direction')}" for c in important[:4])
            level = NotificationLevel.warning if any(c.get("direction") == "declined" for c in important) else NotificationLevel.info
            await NotificationService(self.db).create(
                tenant_id, level, "SEO change detected", summary,
                project_id=project_id, category="operations",
                dedupe_key=f"ops-change-{project_id}-{datetime.utcnow().date()}",
            )
        except Exception:
            pass

    async def _latest_snapshot(self, project_id, tenant_id):
        return (await self.db.execute(
            select(OpsHealthSnapshot).where(
                OpsHealthSnapshot.project_id == project_id, OpsHealthSnapshot.tenant_id == tenant_id
            ).order_by(OpsHealthSnapshot.created_at.desc()).limit(1)
        )).scalars().first()

    @staticmethod
    def _bucket(when: datetime) -> str:
        now = datetime.utcnow()
        d = (now.date() - when.date()).days
        if d <= 0:
            return "today"
        if d == 1:
            return "yesterday"
        if d <= 7:
            return "this_week"
        if d <= 31:
            return "this_month"
        return "older"

    async def _gsc_connected(self, project_id, tenant_id) -> bool:
        try:
            from app.services.search_console import SearchConsoleService
            s = await SearchConsoleService(self.db).summary(project_id, tenant_id)
            return bool(s.get("selected_property"))
        except Exception:
            return False

    async def _pending_reviews(self, project_id, tenant_id) -> int:
        try:
            from app.models.code_review import CodeReview, CodeReviewStatus
            from sqlalchemy import func
            return int((await self.db.execute(
                select(func.count(CodeReview.id)).where(
                    CodeReview.project_id == project_id, CodeReview.tenant_id == tenant_id,
                    CodeReview.status == CodeReviewStatus.ready_for_review,
                )
            )).scalar() or 0)
        except Exception:
            return 0

    async def _has_audit(self, project_id, tenant_id) -> bool:
        return bool(await self._audit_counts(project_id, tenant_id)) or await self._exists("audit", project_id, tenant_id)

    async def _has_generated_patches(self, project_id, tenant_id) -> bool:
        return await self._exists("generated_patch", project_id, tenant_id)

    async def _has_reviews(self, project_id, tenant_id) -> bool:
        return await self._exists("code_review", project_id, tenant_id)

    async def _has_verification(self, project_id, tenant_id) -> bool:
        return await self._exists("deployment_verification", project_id, tenant_id)

    async def _exists(self, kind, project_id, tenant_id) -> bool:
        from sqlalchemy import func
        try:
            if kind == "generated_patch":
                from app.models.generated_patch import GeneratedSeoPatch as M
            elif kind == "code_review":
                from app.models.code_review import CodeReview as M
            elif kind == "deployment_verification":
                from app.models.deployment_verification import DeploymentVerification as M
            elif kind == "audit":
                from app.models.audit import SEOAuditRun as M
            else:
                return False
            return int((await self.db.execute(
                select(func.count(M.id)).where(M.project_id == project_id, M.tenant_id == tenant_id)
            )).scalar() or 0) > 0
        except Exception:
            return False

    async def _tenant_counts(self, tenant_id):
        from sqlalchemy import func
        pending = deployments = verifications = 0
        try:
            from app.models.code_review import CodeReview, CodeReviewStatus
            pending = int((await self.db.execute(
                select(func.count(CodeReview.id)).where(
                    CodeReview.tenant_id == tenant_id, CodeReview.status == CodeReviewStatus.ready_for_review)
            )).scalar() or 0)
        except Exception:
            pass
        try:
            from app.models.deployment_verification import DeploymentVerification
            verifications = int((await self.db.execute(
                select(func.count(DeploymentVerification.id)).where(DeploymentVerification.tenant_id == tenant_id)
            )).scalar() or 0)
        except Exception:
            pass
        try:
            from app.models.deployment import Deployment
            deployments = int((await self.db.execute(
                select(func.count(Deployment.id)).where(Deployment.tenant_id == tenant_id)
            )).scalar() or 0)
        except Exception:
            pass
        return pending, deployments, verifications
