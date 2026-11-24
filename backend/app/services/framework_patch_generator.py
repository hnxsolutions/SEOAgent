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
from app.models.repo_agent import RepoConnection
from app.repo_agent.architecture import RepoArchitectureDetector
from app.repo_agent.project_structure import (
    ProjectStructure,
    REJECTED,
    RESOLVED,
    ResolvedTarget,
    detect_structure,
    resolve_target,
    shadow_root_risk,
    strip_target_hint,
)
from app.repo_agent.scanner import PathSafetyError

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

        # Resolve the repository the patches will actually land in. Without it
        # the generators' template paths ("app/sitemap.ts") cannot be mapped onto
        # the structure the project really uses, so patches are recorded but
        # never marked safe or ready — the generator does not guess paths.
        structure, structure_note = await self._structure(project_id, tenant_id)

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
        rejected = 0
        seen_hashes: set = set()
        seen_targets: Dict[str, str] = {}
        for surface in wanted:
            content = generate_patch(framework_key, surface, ctx)
            if not content:
                continue
            code_hash = hashlib.sha256(content.code.encode("utf-8", "ignore")).hexdigest()
            if code_hash in seen_hashes:
                # e.g. Next.js metadata already carries OG/Twitter — no duplicate row.
                continue
            seen_hashes.add(code_hash)

            resolved = self._resolve(content.target_file, structure, structure_note)
            safe, reason = self._safety_check(resolved.path or content.target_file)
            validation_status, notes = self._validate(
                content, safe, reason, resolved, structure, seen_targets
            )
            if resolved.ok and resolved.path:
                seen_targets[resolved.path] = content.surface
            ready = bool(
                safe
                and content.code_fixable
                and resolved.ok
                and validation_status == GeneratedPatchValidation.passed
            )
            if validation_status == GeneratedPatchValidation.failed:
                rejected += 1
            patch = GeneratedSeoPatch(
                tenant_id=tenant_id, project_id=project_id,
                framework=content.framework, surface=content.surface,
                patch_type=content.patch_type,
                target_file=resolved.path or content.target_file,
                language=content.language, generated_code=content.code,
                # Trust the repository, not the template, for whether this
                # creates a file.
                is_new_file=resolved.is_new_file if resolved.ok else content.is_new_file,
                code_fixable=content.code_fixable,
                explanation=self._explain(content, ctx, resolved), notes=content.notes,
                safe=safe and resolved.ok, safety_reason=reason,
                validation_status=validation_status, validation_notes=notes,
                seo_before=seo_before, performance_before=perf_before,
                ready_for_pr=ready, confidence=confidence,
                code_hash=code_hash,
            )
            self.db.add(patch)
            created += 1

        await self.db.commit()
        logger.info("framework_patches_generated", project_id=str(project_id),
                    framework=framework_key, count=created, rejected=rejected,
                    structure=structure.router if structure else "unavailable")
        result: Dict[str, Any] = {
            "status": "generated", "generated": created, "framework": framework_key,
            "surfaces": wanted, "rejected": rejected,
        }
        if structure is None:
            result["structure"] = "unavailable"
            result["note"] = structure_note
        else:
            result["structure"] = structure.router
            result["app_root"] = structure.app_prefix or structure.pages_prefix
            if structure.ambiguous:
                result["note"] = structure.ambiguity_reason
        return result

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
            from urllib.parse import urlparse

            paths = []
            for p in pages:
                url = getattr(p, "normalized_url", None) or getattr(p, "url", "")
                if not url or getattr(p, "status_code", 200) != 200 or getattr(p, "noindex", False):
                    continue
                # Treat scheme-less values (bare host) as a full URL so the host
                # never leaks into the path.
                raw = url if "://" in url else "https://" + url.lstrip("/")
                path = urlparse(raw).path
                path = "/" + path.strip("/") if path.strip("/") else "/"
                paths.append(path)
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

    async def _structure(
        self, project_id: UUID, tenant_id: UUID
    ) -> tuple[Optional[ProjectStructure], str]:
        """Detect the structure of the repository connected to this project.

        Returns ``(None, reason)`` when no usable checkout is reachable. The
        caller must then refuse to mark any patch safe or ready, rather than
        falling back to the generators' template paths.
        """
        connections = (await self.db.execute(
            select(RepoConnection).where(
                RepoConnection.project_id == project_id,
                RepoConnection.tenant_id == tenant_id,
            ).order_by(RepoConnection.updated_at.desc())
        )).scalars().all()
        if not connections:
            return None, "No repository is connected to this project, so patch targets cannot be resolved."

        errors = []
        for connection in connections:
            if not connection.local_path:
                errors.append("a connection has no local_path")
                continue
            try:
                return detect_structure(connection.local_path), ""
            except PathSafetyError as exc:
                errors.append(f"{connection.local_path}: {exc}")
        return None, "Repository checkout is not reachable (" + "; ".join(errors) + ")."

    def _resolve(
        self, target_file: str, structure: Optional[ProjectStructure], structure_note: str
    ) -> ResolvedTarget:
        if structure is None:
            return ResolvedTarget(
                original=target_file,
                status=REJECTED,
                reason=structure_note or "Repository unavailable; refusing to guess a path.",
            )
        return resolve_target(target_file, structure)

    def _safety_check(self, target_file: str) -> tuple[bool, Optional[str]]:
        """Reuse the shared Patch Safety classifier's protected-path guard. SEO
        files pass; anything touching UI/business/auth/payments/DB is rejected."""
        # strip parenthetical hints like "app/page.tsx (metadata export)"
        path = strip_target_hint(target_file)
        if self._safety._is_unsafe_path(path):
            return False, "Target path is a protected (UI/business/auth/payments/DB) area."
        return True, "SEO-safe target (metadata/robots/sitemap/schema surface only)."

    def _validate(
        self,
        content,
        safe: bool,
        reason: Optional[str],
        resolved: ResolvedTarget,
        structure: Optional[ProjectStructure],
        seen_targets: Optional[Dict[str, str]] = None,
    ) -> tuple[GeneratedPatchValidation, dict]:
        """Validate a generated patch against the repository it would land in.

        A patch is only ``passed`` when its target resolves inside the connected
        checkout, matches the structure the project actually uses, and does not
        collide with an existing file or another patch in the same run. Checks
        that did not run are reported as gated — never as passed.
        """
        notes: Dict[str, Any] = {}
        failures: List[str] = []
        notes["safety"] = reason

        # 1-2. Target resolves, and onto the structure this project really uses.
        notes["target_resolution"] = resolved.status
        notes["target_reason"] = resolved.reason
        if resolved.original and resolved.path and strip_target_hint(resolved.original) != resolved.path:
            notes["target_remapped_from"] = strip_target_hint(resolved.original)
        if structure is not None:
            notes["project_structure"] = (
                f"{structure.router} router at "
                f"{structure.app_prefix or structure.pages_prefix or 'unknown'}"
            )
            notes["language"] = "typescript" if structure.typescript else "javascript"
        else:
            notes["project_structure"] = "unavailable"

        if not safe:
            failures.append("safety: target is a protected area")
        if resolved.status != RESOLVED:
            failures.append(f"target_resolution: {resolved.reason}")

        # 5. A target that would introduce a competing application root is never
        # safe, whatever surface it claims to be.
        if structure is not None and resolved.path:
            shadow = shadow_root_risk(resolved.path, structure)
            if shadow:
                notes["shadow_root"] = shadow
                failures.append(f"shadow_root: {shadow}")
            else:
                notes["shadow_root"] = "none: target is inside the active application root"

        # 3-4. Existing vs new file must match reality on disk.
        if resolved.status == RESOLVED:
            notes["target_exists"] = resolved.exists
            if content.is_new_file and resolved.exists:
                failures.append(
                    f"new_file_conflict: {resolved.path} already exists; refusing to overwrite it "
                    "with generated content"
                )
            notes["file_mode"] = "create" if resolved.is_new_file else "update"

        # 6. Two patches in one run must not target the same file.
        if seen_targets and resolved.path and resolved.path in seen_targets:
            failures.append(
                f"duplicate_target: {resolved.path} is already targeted by the "
                f"{seen_targets[resolved.path]} patch in this run"
            )

        # 7. Patch type must suit the target it was mapped onto.
        type_problem = self._patch_type_mismatch(content, resolved)
        if type_problem:
            failures.append(f"patch_type: {type_problem}")
        else:
            notes["patch_type_check"] = "passed"

        # Static structural checks appropriate to the language.
        code = content.code or ""
        static_ok = bool(code.strip())
        if content.language in ("typescript", "tsx", "javascript"):
            static_ok = static_ok and code.count("{") == code.count("}") and code.count("(") == code.count(")")
        if content.language in ("json", "xml"):
            static_ok = static_ok and ("<" in code or "{" in code)
        notes["static_structure"] = "passed" if static_ok else "failed: unbalanced/empty"
        if not static_ok:
            failures.append("static_structure: generated code is empty or unbalanced")

        # 9. Only ever claim a check that actually ran.
        notes["typecheck"] = "gated: not run (requires installing and compiling the project)"
        notes["lint"] = "gated: not run (requires the project's own lint setup)"
        notes["build"] = "gated: not run (requires a full project build)"
        notes["pagespeed_cwv"] = "gated: measured after apply + deploy (before/after)"
        if not content.code_fixable:
            notes["apply"] = "guided setting (not an auto-appliable code file)"

        if failures:
            notes["failures"] = failures
            notes["summary"] = failures[0]
            return GeneratedPatchValidation.failed, notes

        notes["summary"] = (
            f"Structural checks passed against the connected repository; target {resolved.path}."
        )
        return GeneratedPatchValidation.passed, notes

    @staticmethod
    def _patch_type_mismatch(content, resolved: ResolvedTarget) -> Optional[str]:
        """Check the surface against the file it was mapped onto."""
        if resolved.status != RESOLVED or not resolved.path:
            return None
        path = resolved.path
        expectations = {
            "sitemap": ("sitemap", "a sitemap route or public/sitemap.xml"),
            "robots": ("robots", "a robots route or public/robots.txt"),
        }
        expected = expectations.get(content.surface)
        if expected and expected[0] not in path.rsplit("/", 1)[-1].lower():
            return f"{content.surface} patch targets {path}, which is not {expected[1]}"
        return None

    async def _confidence(self, framework_key: str, tenant_id: UUID) -> int:
        """Evidence-based confidence: the Learning Engine's verification history,
        adjusted by human code-review outcomes for this framework (approvals
        raise, rejections lower it), falling back to a conservative base."""
        base = _BASE_CONFIDENCE.get(framework_key, 70)
        try:
            from app.services.learning import LearningEngine

            learned = await LearningEngine(self.db).evidence_confidence("metadata_update", tenant_id)
            if learned:
                base = int(learned)
        except Exception:
            pass
        # Blend in human review evidence for this framework.
        try:
            from app.services.code_review import CodeReviewService

            ev = await CodeReviewService(self.db).framework_evidence(tenant_id, framework_key)
            total = ev["approved"] + ev["rejected"]
            if total:
                ratio = ev["approved"] / total          # 0..1
                base = int(round(base * 0.7 + (60 + ratio * 40) * 0.3))
        except Exception:
            pass
        return max(30, min(99, base))

    @staticmethod
    def _explain(content, ctx: PatchContext, resolved: Optional[ResolvedTarget] = None) -> str:
        target = (resolved.path if resolved and resolved.path else content.target_file)
        base = (f"Framework-native {content.surface} patch for {content.framework} "
                f"targeting {target}. SEO-safe only — head/config surface, "
                f"no UI, layout, business logic, auth, payments, CRM or database changes.")
        if resolved and resolved.status != RESOLVED:
            return base + f" NOT APPLICABLE: {resolved.reason}"
        if resolved and resolved.path and strip_target_hint(resolved.original) != resolved.path:
            return base + (f" Target was mapped from the framework template path "
                           f"{strip_target_hint(resolved.original)} onto this repository's structure.")
        return base

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
