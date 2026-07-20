"""Technology Fingerprint service.

Fetches the live website (homepage HTML + response headers + robots.txt + a
sitemap probe — no credentials required), runs the deterministic detector, and —
when a repository is connected — merges the existing repo architecture profile so
the fingerprint reflects both what the site serves and what the codebase is. The
result is persisted once per project and reused everywhere; it is only recomputed
when the caller forces a re-analyze.

This service NEVER modifies the target website. It only reads public signals to
classify the stack, so the SEO engine can later choose a framework-appropriate,
SEO-safe patch strategy.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.fingerprint.detector import (
    DetectedTech,
    FingerprintResult,
    SiteSignals,
    TechnologyFingerprintDetector,
)
from app.models.fingerprint import FingerprintSource, FingerprintStatus, TechnologyFingerprint
from app.models.project import Project
from app.models.repo_agent import RepoConnection

logger = structlog.get_logger(__name__)

_FETCH_TIMEOUT = 12.0
_UA = "Mozilla/5.0 (compatible; SEOAgentFingerprint/1.0; +https://seoagent.local/bot)"


class FingerprintService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.detector = TechnologyFingerprintDetector()

    # -- read ---------------------------------------------------------------

    async def get(self, project_id: UUID, tenant_id: UUID) -> Optional[TechnologyFingerprint]:
        return (await self.db.execute(
            select(TechnologyFingerprint).where(
                TechnologyFingerprint.project_id == project_id,
                TechnologyFingerprint.tenant_id == tenant_id,
            )
        )).scalars().first()

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Compact, business-friendly view for Mission Control / Daily Briefing.

        Degrades gracefully: if no fingerprint exists yet, returns a
        not-analyzed shape rather than raising."""
        fp = await self.get(project_id, tenant_id)
        if not fp:
            return {
                "status": "not_analyzed",
                "detected": False,
                "note": "Technology not analyzed yet. Run Re-analyze Technology.",
                "scores": {},
                "technologies": [],
            }
        return {
            "status": self._enum(fp.status),
            "detected": fp.status == FingerprintStatus.complete,
            "source": self._enum(fp.source),
            "primary_framework": fp.primary_framework,
            "primary_cms": fp.primary_cms,
            "primary_language": fp.primary_language,
            "rendering": fp.rendering,
            "hosting": fp.hosting,
            "cdn": fp.cdn,
            "scores": fp.scores or {},
            "technologies": fp.technologies or [],
            "by_category": self._group(fp.technologies or []),
            "detected_at": fp.detected_at.isoformat() if fp.detected_at else None,
            "error": fp.error,
        }

    # -- analyze ------------------------------------------------------------

    async def analyze(
        self, project_id: UUID, tenant_id: UUID, force: bool = False
    ) -> TechnologyFingerprint:
        """Detect (or reuse) the project's technology fingerprint.

        Reuse rule: if a completed fingerprint exists and force is False, return
        it untouched — the stack is not re-detected unless the user asks."""
        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")

        existing = await self.get(project_id, tenant_id)
        if existing and existing.status == FingerprintStatus.complete and not force:
            return existing

        fp = existing or TechnologyFingerprint(tenant_id=tenant_id, project_id=project_id)
        fp.status = FingerprintStatus.detecting
        fp.source_url = self._project_url(project.domain)
        if not existing:
            self.db.add(fp)
        await self.db.commit()

        try:
            signals = await self._fetch_signals(fp.source_url)
            result = self.detector.detect(signals)
            source = FingerprintSource.url

            repo_techs = await self._repo_architecture(project_id, tenant_id)
            if repo_techs:
                result = self._merge_repo(result, repo_techs)
                source = FingerprintSource.hybrid

            self._apply(fp, result, source)
            fp.status = FingerprintStatus.complete
            fp.error = None
            fp.detected_at = datetime.utcnow()
            logger.info(
                "fingerprint_detected",
                project_id=str(project_id),
                framework=fp.primary_framework,
                cms=fp.primary_cms,
                source=source.value,
            )
        except Exception as exc:  # graceful — record failure, never fabricate
            fp.status = FingerprintStatus.failed
            fp.error = str(exc)[:500]
            logger.warning("fingerprint_failed", project_id=str(project_id), error=str(exc))

        await self.db.commit()
        await self.db.refresh(fp)
        return fp

    # -- fetching -----------------------------------------------------------

    async def _fetch_signals(self, url: str) -> SiteSignals:
        headers: Dict[str, str] = {}
        html = ""
        status_code: Optional[int] = None
        final_url = url
        robots_txt: Optional[str] = None
        has_sitemap = False

        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            resp = await client.get(url)
            status_code = resp.status_code
            final_url = str(resp.url)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            html = resp.text or ""

            base = f"{httpx.URL(final_url).scheme}://{httpx.URL(final_url).host}"
            try:
                r = await client.get(base + "/robots.txt")
                if r.status_code == 200 and "text" in r.headers.get("content-type", ""):
                    robots_txt = r.text
            except Exception:
                robots_txt = None

            if robots_txt and "sitemap:" in robots_txt.lower():
                has_sitemap = True
            else:
                try:
                    sm = await client.get(base + "/sitemap.xml")
                    has_sitemap = sm.status_code == 200 and "xml" in sm.headers.get("content-type", "").lower()
                except Exception:
                    has_sitemap = False

        return SiteSignals(
            url=url,
            status_code=status_code,
            headers=headers,
            html=html,
            robots_txt=robots_txt,
            has_sitemap=has_sitemap,
            final_url=final_url,
        )

    async def _repo_architecture(self, project_id: UUID, tenant_id: UUID) -> List[DetectedTech]:
        """If a repo is connected with a local checkout, fold its architecture in."""
        conn = (await self.db.execute(
            select(RepoConnection).where(
                RepoConnection.project_id == project_id,
                RepoConnection.tenant_id == tenant_id,
            ).order_by(RepoConnection.created_at.desc()).limit(1)
        )).scalars().first()
        if not conn or not conn.local_path:
            return []
        root = Path(conn.local_path)
        if not root.exists():
            return []
        try:
            from app.repo_agent.architecture import RepoArchitectureDetector

            data = RepoArchitectureDetector().detect(root).as_record()
        except Exception as exc:
            logger.warning("fingerprint_repo_detect_failed", error=str(exc))
            return []

        out: List[DetectedTech] = []
        stack = data.get("framework") or data.get("detected_stack")
        conf = int(round(float(data.get("confidence_score") or 0) * 100))
        if stack and stack != "unknown_custom":
            notes = [n.get("reason", "") for n in (data.get("detection_notes") or []) if n.get("reason")]
            out.append(DetectedTech("framework", str(stack).replace("_", " ").title(), max(conf, 50),
                                    notes[:4] or ["Detected from connected repository"]))
        pkg = data.get("package_manager")
        if pkg:
            out.append(DetectedTech("package_manager", str(pkg), 80, ["Detected from repository manifest"]))
        build = data.get("build_system")
        if build:
            out.append(DetectedTech("build_system", str(build), 78, ["Detected from repository config"]))
        return out

    # -- merge + persist ----------------------------------------------------

    @staticmethod
    def _merge_repo(result: FingerprintResult, repo_techs: List[DetectedTech]) -> FingerprintResult:
        by_key = {(t.category, t.name.lower()): t for t in result.technologies}
        for rt in repo_techs:
            key = (rt.category, rt.name.lower())
            existing = by_key.get(key)
            if existing:
                # Repo confirmation strengthens the URL signal.
                existing.confidence = min(99, max(existing.confidence, rt.confidence) + 2)
                for e in rt.evidence:
                    if e and e not in existing.evidence:
                        existing.evidence.append(e)
            else:
                result.technologies.append(rt)
                by_key[key] = rt
        # Primary framework: prefer a repo-confirmed framework if URL had none.
        if not result.primary_framework:
            fw = next((t for t in repo_techs if t.category == "framework"), None)
            if fw:
                result.primary_framework = fw.name
        return result

    def _apply(self, fp: TechnologyFingerprint, result: FingerprintResult, source: FingerprintSource) -> None:
        fp.technologies = result.technologies_as_dicts()
        fp.scores = result.scores
        fp.primary_framework = result.primary_framework
        fp.primary_cms = result.primary_cms
        fp.primary_language = result.primary_language
        fp.rendering = result.rendering
        fp.hosting = result.hosting
        fp.cdn = result.cdn
        fp.content_hash = result.content_hash
        fp.source = source

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _group(techs: List[dict]) -> Dict[str, List[dict]]:
        grouped: Dict[str, List[dict]] = {}
        for t in techs:
            grouped.setdefault(t.get("category", "other"), []).append(t)
        return grouped

    @staticmethod
    def _project_url(domain: str) -> str:
        raw = (domain or "").strip()
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = "https://" + raw
        return raw.rstrip("/")

    @staticmethod
    def _enum(value):
        return getattr(value, "value", value)
