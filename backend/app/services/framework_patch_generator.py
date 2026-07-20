"""Framework-aware SEO patch generator service.

Turns framework-specific SEO tasks into real, SEO-safe code patches. It composes:

    Technology Fingerprint  ->  detected framework
    Framework Strategy      ->  which SEO surfaces matter
    Framework Knowledge Base->  how this framework does SEO
    per-framework generator ->  the actual code

Each generated patch is validated (static structure + the shared Patch Safety
classifier) and recorded. Full build / PageSpeed / Core Web Vitals validation is
honestly marked as gated when the project has no connected repo/deployment — the
service never fabricates a build result or an "after" score.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.framework_kb import normalize_framework_key
from app.framework_patches import PatchContext, SUPPORTED_SURFACES, generate_patch, generator_for
from app.models.crawl import CrawlJob, CrawlPage, CrawlStatus
from app.models.generated_patch import GeneratedPatchValidation, GeneratedSeoPatch
from app.models.project import Project
from app.repo_agent.architecture import RepoArchitectureDetector

logger = structlog.get_logger(__name__)

# Default per-framework confidence when no verification history exists yet.
_BASE_CONFIDENCE = {"nextjs": 85, "nuxt": 82, "astro": 82, "sveltekit": 78, "gatsby": 78,
                    "django": 75, "laravel": 75, "custom": 70, "react": 65, "vue": 65,
                    "angular": 62, "wordpress": 68, "shopify": 68}


class FrameworkPatchGeneratorService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._safety = RepoArchitectureDetector()

    # -- generate -----------------------------------------------------------

    async def generate(
        self, project_id: UUID, tenant_id: UUID, surfaces: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generate framework-specific SEO patches for the project's detected
        stack. Degrades gracefully when technology has not been analyzed yet."""
        from app.services.fingerprint import FingerprintService

        project = (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()
        if not project:
            raise ValueError("Project not found")

        summary = await FingerprintService(self.db).summary(project_id, tenant_id)
        if not summary.get("detected"):
            return {"status": "not_analyzed", "generated": 0,
                    "note": "Run Re-analyze Technology first — the generator needs the detected framework."}

        strategy = summary.get("strategy") or {}
        framework_key = strategy.get("primary_framework_key") or normalize_framework_key(
            summary.get("primary_cms") or summary.get("primary_framework")
        )
        if not generator_for(framework_key):
            return {"status": "unsupported_framework", "generated": 0,
                    "framework": summary.get("primary_framework"),
                    "note": "No dedicated generator for this stack; SEO changes stay head-only + manual."}

        ctx = await self._context(project, framework_key)
        wanted = surfaces or self._surfaces_for(summary)
        confidence = await self._confidence(framework_key, tenant_id)
        seo_before = (summary.get("scores") or {}).get("seo_readiness")
        perf_before = (summary.get("scores") or {}).get("performance_readiness")

        # Replace any prior generation for this project (idempotent re-generate).
        existing = (await self.db.execute(
            select(GeneratedSeoPatch).where(GeneratedSeoPatch.project_id == project_id)
        )).scalars().all()
        for row in existing:
            await self.db.delete(row)

        created = 0
        seen_hashes: set = set()
        for surface in wanted:
            content = generate_patch(framework_key, surface, ctx)
            if not content:
                continue
            code_hash = hashlib.sha256(content.code.encode("utf-8", "ignore")).hexdigest()
            if code_hash in seen_hashes:
                # e.g. Next.js metadata already carries OG/Twitter — no duplicate row.
                continue
            seen_hashes.add(code_hash)
            safe, reason = self._safety_check(content.target_file)
            validation_status, notes = self._validate(content, safe, reason)
            ready = bool(safe and content.code_fixable and validation_status == GeneratedPatchValidation.passed)
            patch = GeneratedSeoPatch(
                tenant_id=tenant_id, project_id=project_id,
                framework=content.framework, surface=content.surface,
                patch_type=content.patch_type, target_file=content.target_file,
                language=content.language, generated_code=content.code,
                is_new_file=content.is_new_file, code_fixable=content.code_fixable,
                explanation=self._explain(content, ctx), notes=content.notes,
                safe=safe, safety_reason=reason,
                validation_status=validation_status, validation_notes=notes,
                seo_before=seo_before, performance_before=perf_before,
                ready_for_pr=ready, confidence=confidence,
                code_hash=code_hash,
            )
            self.db.add(patch)
            created += 1

        await self.db.commit()
        logger.info("framework_patches_generated", project_id=str(project_id),
                    framework=framework_key, count=created)
        return {"status": "generated", "generated": created, "framework": framework_key,
                "surfaces": wanted}

    # -- context ------------------------------------------------------------

    async def _context(self, project: Project, framework_key: str) -> PatchContext:
        domain = (project.domain or "").strip()
        site_url = domain if domain.startswith("http") else "https://" + domain
        routes = await self._routes(project.id, project.tenant_id)
        return PatchContext(
            framework_key=framework_key,
            site_url=site_url.rstrip("/"),
            page_label=project.business_name or project.name or "Home",
            page_path="/",
            business_name=project.business_name or project.name or "",
            description=(project.seo_goal or "")[:180],
            routes=routes,
        )

    async def _routes(self, project_id: UUID, tenant_id: UUID) -> List[str]:
        """Real crawled paths for the sitemap (falls back to ['/'])."""
        try:
            job = (await self.db.execute(
                select(CrawlJob).where(
                    CrawlJob.project_id == project_id, CrawlJob.status == CrawlStatus.completed
                ).order_by(CrawlJob.created_at.desc()).limit(1)
            )).scalars().first()
            if not job:
                return ["/"]
            pages = (await self.db.execute(
                select(CrawlPage).where(CrawlPage.crawl_job_id == job.id).limit(50)
            )).scalars().all()
            paths = []
            for p in pages:
                url = getattr(p, "normalized_url", None) or getattr(p, "url", "")
                path = "/" + url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
                if getattr(p, "status_code", 200) == 200 and not getattr(p, "noindex", False):
                    paths.append(path if path.startswith("/") else "/" + path)
            uniq = sorted(set(paths))[:30]
            return uniq or ["/"]
        except Exception:
            return ["/"]

    def _surfaces_for(self, summary: Dict[str, Any]) -> List[str]:
        """Prioritise SEO surfaces missing from the live site, but always cover
        the framework's core surfaces so the generator is useful."""
        names = {(t.get("name") or "").lower() for t in summary.get("technologies", [])}
        cats = {t.get("category") for t in summary.get("technologies", [])}
        missing = []
        if not any("canonical" in n or "title" in n for n in names):
            missing.append("metadata")
        if "sitemap" not in cats:
            missing.append("sitemap")
        if "robots" not in cats:
            missing.append("robots")
        if not any("json-ld" in n or "schema" in n for n in names):
            missing.append("schema")
        if not any("open graph" in n for n in names):
            missing.append("og_twitter")
        # Always offer the full set; missing ones are simply the highest value.
        ordered = missing + [s for s in SUPPORTED_SURFACES if s not in missing]
        return ordered

    # -- validation + safety ------------------------------------------------

    def _safety_check(self, target_file: str) -> tuple[bool, Optional[str]]:
        """Reuse the shared Patch Safety classifier's protected-path guard. SEO
        files pass; anything touching UI/business/auth/payments/DB is rejected."""
        # strip parenthetical hints like "app/page.tsx (metadata export)"
        path = target_file.split(" (")[0].strip()
        if self._safety._is_unsafe_path(path):
            return False, "Target path is a protected (UI/business/auth/payments/DB) area."
        return True, "SEO-safe target (metadata/robots/sitemap/schema surface only)."

    def _validate(self, content, safe: bool, reason: Optional[str]) -> tuple[GeneratedPatchValidation, dict]:
        notes: Dict[str, Any] = {}
        if not safe:
            notes["safety"] = reason
            return GeneratedPatchValidation.failed, notes

        code = content.code or ""
        # Static structural checks appropriate to the language.
        static_ok = bool(code.strip())
        if content.language in ("typescript", "tsx", "javascript"):
            static_ok = static_ok and code.count("{") == code.count("}") and code.count("(") == code.count(")")
        if content.language in ("json", "xml"):
            static_ok = static_ok and ("<" in code or "{" in code)
        notes["static_structure"] = "passed" if static_ok else "failed: unbalanced/empty"
        notes["safety"] = reason

        if not static_ok:
            return GeneratedPatchValidation.failed, notes

        # Full validation requires the real project — mark honestly as gated.
        notes["typecheck"] = "gated: run on a connected repository"
        notes["lint"] = "gated: run on a connected repository"
        notes["build"] = "gated: run on a connected repository"
        notes["pagespeed_cwv"] = "gated: measured after apply + deploy (before/after)"
        if not content.code_fixable:
            notes["apply"] = "guided setting (not an auto-appliable code file)"
        # Static + safety passed. This is a real, reviewable, SEO-safe patch.
        return GeneratedPatchValidation.passed, notes

    async def _confidence(self, framework_key: str, tenant_id: UUID) -> int:
        """Reuse the Learning Engine's evidence-based confidence where available;
        otherwise a conservative per-framework base."""
        try:
            from app.services.learning import LearningEngine

            learned = await LearningEngine(self.db).evidence_confidence("metadata_update", tenant_id)
            if learned:
                return int(learned)
        except Exception:
            pass
        return _BASE_CONFIDENCE.get(framework_key, 70)

    @staticmethod
    def _explain(content, ctx: PatchContext) -> str:
        return (f"Framework-native {content.surface} patch for {content.framework} "
                f"targeting {content.target_file}. SEO-safe only — head/config surface, "
                f"no UI, layout, business logic, auth, payments, CRM or database changes.")

    # -- read ---------------------------------------------------------------

    async def list_patches(self, project_id: UUID, tenant_id: UUID) -> List[GeneratedSeoPatch]:
        rows = await self.db.execute(
            select(GeneratedSeoPatch).where(
                GeneratedSeoPatch.project_id == project_id,
                GeneratedSeoPatch.tenant_id == tenant_id,
            ).order_by(GeneratedSeoPatch.ready_for_pr.desc(), GeneratedSeoPatch.created_at.desc())
        )
        return list(rows.scalars().all())

    async def get_patch(self, patch_id: UUID, tenant_id: UUID) -> Optional[GeneratedSeoPatch]:
        return (await self.db.execute(
            select(GeneratedSeoPatch).where(
                GeneratedSeoPatch.id == patch_id, GeneratedSeoPatch.tenant_id == tenant_id
            )
        )).scalars().first()

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        rows = (await self.db.execute(
            select(GeneratedSeoPatch.validation_status, func.count(GeneratedSeoPatch.id))
            .where(GeneratedSeoPatch.project_id == project_id, GeneratedSeoPatch.tenant_id == tenant_id)
            .group_by(GeneratedSeoPatch.validation_status)
        )).all()
        by_status = {getattr(s, "value", s): int(c) for s, c in rows}
        ready = int((await self.db.execute(
            select(func.count(GeneratedSeoPatch.id)).where(
                GeneratedSeoPatch.project_id == project_id,
                GeneratedSeoPatch.tenant_id == tenant_id,
                GeneratedSeoPatch.ready_for_pr.is_(True),
            )
        )).scalar() or 0)
        framework = (await self.db.execute(
            select(GeneratedSeoPatch.framework).where(
                GeneratedSeoPatch.project_id == project_id, GeneratedSeoPatch.tenant_id == tenant_id
            ).limit(1)
        )).scalar()
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
            "ready_for_pr": ready,
            "framework": framework,
        }
