"""Builds the agent's understanding of a website, and knows when not to rebuild it.

Two passes, in this order, because the cheap one answers most of it:

1. **Deterministic extraction** from the latest crawl — navigation shape, page
   roles (home/about/services/contact/blog), repeated brand terms, locations,
   topics from titles and headings. No model, no network, runs in milliseconds.
2. **Local-model inference**, only for the things extraction genuinely cannot
   decide: what kind of business this is, its niche, who it is for. One call,
   and only when step 1 left those blank.

Two rules the rest of the system depends on:

**User-stated facts outrank inference, always.** If the project brief says the
industry is "Healthcare", no amount of model confidence overwrites it. The
profile records which half each field came from, so a dashboard can show
"Healthcare (confirmed)" next to "B2B SaaS (inferred, 0.72)" and a reader can
tell them apart.

**Identical content is never re-inferred.** The hash of the pages the profile
was built from is stored; an unchanged site reuses the profile. That is what
keeps a 99-second local model call out of a scheduler tick that runs every
fifteen minutes.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlPage
from app.models.project import Project
from app.models.website_profile import (
    ProfileFieldSource,
    WebsiteProfile,
    WebsiteProfileSnapshot,
    WebsiteProfileStatus,
)
from app.services.content_engine import latest_completed_crawl

logger = structlog.get_logger(__name__)


#: Pages whose role can be read from the URL alone. Ordered by how much they
#: say about the business.
PAGE_ROLE_PATTERNS: Sequence[Tuple[str, Tuple[str, ...]]] = (
    ("home", ("",)),
    ("about", ("about", "about-us", "who-we-are", "our-story", "company")),
    ("services", ("service", "services", "what-we-do", "solutions", "offerings")),
    ("products", ("product", "products", "shop", "store", "catalog")),
    ("pricing", ("pricing", "plans", "packages")),
    ("contact", ("contact", "contact-us", "get-in-touch", "book", "appointment")),
    ("blog", ("blog", "articles", "insights", "news", "resources")),
    ("case_study", ("case-study", "case-studies", "work", "portfolio", "projects")),
)

#: Fields the project owner can state directly. Inference never overwrites a
#: value present in any of these.
USER_FIELD_MAP = {
    "business_name": "business_name",
    "industry": "industry",
    "target_audience": "target_audience",
    "services": "primary_services",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'&-]{2,}")
_STOP = frozenset(
    """the and for you our with from this that are was all can has have how what
    why who your their its more most best top new get out use using about into
    over under than then them they will would should could been being were
    home page site web click here read learn view find contact menu skip""".split()
)


class WebsiteProfileService:
    """Creates, reuses and versions one profile per project."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def get(self, project_id: UUID, tenant_id: UUID) -> Optional[WebsiteProfile]:
        result = await self.db.execute(
            select(WebsiteProfile).where(
                WebsiteProfile.project_id == project_id,
                WebsiteProfile.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def build(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        force: bool = False,
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """Build or refresh the profile.

        Returns a summary including whether anything was actually recomputed,
        so a caller (and a scheduled job) can see that reuse is working.
        """
        project = await self._project(project_id, tenant_id)
        if not project:
            return {"status": "skipped", "reason": "Project not found."}

        pages = await self._pages(project_id, tenant_id)
        if not pages:
            return {
                "status": "skipped",
                "reason": "No completed crawl yet — the profile is built from the site's own pages.",
            }

        content_hash = self._hash(pages)
        existing = await self.get(project_id, tenant_id)

        if existing and existing.content_hash == content_hash and not force:
            # The site has not changed since this profile was built. Rebuilding
            # would cost a model call and produce the same answer.
            return {
                "status": "reused",
                "profile_id": str(existing.id),
                "version": existing.version,
                "reason": "Website content is unchanged since the last profile.",
            }

        extracted = self._extract(project, pages)
        inferred: Dict[str, Any] = {}
        used_llm = "no"

        missing = [k for k in ("business_type", "niche", "target_audience") if not extracted.get(k)]
        if use_llm and missing:
            inferred = await self._infer(project, pages, missing)
            used_llm = "yes" if inferred else "failed"

        profile = await self._persist(
            project=project,
            tenant_id=tenant_id,
            existing=existing,
            extracted=extracted,
            inferred=inferred,
            content_hash=content_hash,
            used_llm=used_llm,
            pages=pages,
        )

        return {
            "status": "built",
            "profile_id": str(profile.id),
            "version": profile.version,
            "confidence": profile.confidence,
            "used_llm": profile.used_llm,
            "pages_analysed": len(pages),
        }

    def to_dict(self, profile: WebsiteProfile) -> Dict[str, Any]:
        """Shape the dashboard reads — every field carries its provenance."""
        def field(name: str, value: Any) -> Dict[str, Any]:
            source = (profile.field_sources or {}).get(name, ProfileFieldSource.unknown.value)
            return {
                "value": value,
                "source": source,
                "confirmed": source == ProfileFieldSource.user.value,
                "confidence": (profile.field_confidence or {}).get(name),
                "evidence": (profile.field_evidence or {}).get(name),
            }

        return {
            "profile_id": str(profile.id),
            "version": profile.version,
            "status": profile.status.value if hasattr(profile.status, "value") else profile.status,
            "confidence": profile.confidence,
            "used_llm": profile.used_llm,
            "generated_at": profile.generated_at.isoformat() if profile.generated_at else None,
            "fields": {
                "business_name": field("business_name", profile.business_name),
                "business_type": field("business_type", profile.business_type),
                "industry": field("industry", profile.industry),
                "niche": field("niche", profile.niche),
                "description": field("description", profile.description),
                "services": field("services", profile.services or []),
                "products": field("products", profile.products or []),
                "locations": field("locations", profile.locations or []),
                "primary_topics": field("primary_topics", profile.primary_topics or []),
                "brand_terms": field("brand_terms", profile.brand_terms or []),
                "target_audience": field("target_audience", profile.target_audience),
            },
            "important_pages": profile.important_pages or [],
        }

    # ------------------------------------------------------------------
    # Pass 1 — deterministic
    # ------------------------------------------------------------------

    def _extract(self, project: Project, pages: Sequence[CrawlPage]) -> Dict[str, Any]:
        """Everything readable without a model."""
        roles = self._page_roles(pages)
        titles = [p.title or "" for p in pages if p.title]
        brand = self._brand_terms(titles)

        return {
            "business_name": project.business_name or (brand[0] if brand else None),
            "brand_terms": brand,
            "services": self._services(pages, roles),
            "products": [r["title"] for r in roles.get("products", [])][:10],
            "primary_topics": self._topics(pages),
            "locations": self._locations(pages, project),
            "description": self._description(pages, roles),
            "important_pages": [
                {"url": item["url"], "title": item["title"], "role": role}
                for role, items in roles.items()
                for item in items[:3]
            ],
            # Left for inference unless the brief already states them.
            "business_type": None,
            "niche": None,
            "target_audience": project.target_audience,
            "industry": project.industry,
        }

    def _page_roles(self, pages: Sequence[CrawlPage]) -> Dict[str, List[Dict[str, str]]]:
        roles: Dict[str, List[Dict[str, str]]] = {}
        for page in pages:
            path = (page.url or "").split("://", 1)[-1]
            path = path.split("/", 1)[1].strip("/").lower() if "/" in path else ""
            first = path.split("/", 1)[0] if path else ""
            for role, patterns in PAGE_ROLE_PATTERNS:
                if first in patterns:
                    roles.setdefault(role, []).append(
                        {"url": page.url or "", "title": page.title or first or "Home"}
                    )
                    break
        return roles

    def _services(self, pages: Sequence[CrawlPage], roles: Dict[str, List[Dict[str, str]]]) -> List[str]:
        """Service names from service-page titles, cleaned of boilerplate."""
        names: List[str] = []
        for item in roles.get("services", []):
            title = re.split(r"[|\-–—:]", item["title"])[0].strip()
            if title and len(title) < 80:
                names.append(title)
        return list(dict.fromkeys(names))[:12]

    def _topics(self, pages: Sequence[CrawlPage]) -> List[str]:
        """The words this site actually keeps talking about."""
        counter: Counter = Counter()
        for page in pages:
            blob = f"{page.title or ''} {page.meta_description or ''}"
            for word in _WORD.findall(blob.lower()):
                if word not in _STOP and len(word) > 3:
                    counter[word] += 1
        return [word for word, count in counter.most_common(15) if count > 1]

    def _locations(self, pages: Sequence[CrawlPage], project: Project) -> List[str]:
        if project.target_location:
            return [project.target_location]
        # Only claim a location when the site repeats it; a single mention in a
        # footer is not evidence that a business serves a place.
        counter: Counter = Counter()
        for page in pages:
            for match in re.findall(r"\b(?:in|near|serving)\s+([A-Z][a-z]{3,})", page.title or ""):
                counter[match] += 1
        return [name for name, count in counter.most_common(5) if count >= 2]

    def _description(self, pages: Sequence[CrawlPage], roles: Dict[str, List[Dict[str, str]]]) -> Optional[str]:
        """The homepage's own description of itself, preferred over anything derived."""
        home_urls = {item["url"] for item in roles.get("home", [])}
        for page in pages:
            if page.url in home_urls and page.meta_description:
                return page.meta_description[:1000]
        for page in pages:
            if page.meta_description:
                return page.meta_description[:1000]
        return None

    # ------------------------------------------------------------------
    # Pass 2 — local model, only for what extraction cannot decide
    # ------------------------------------------------------------------

    async def _infer(
        self, project: Project, pages: Sequence[CrawlPage], missing: Sequence[str]
    ) -> Dict[str, Any]:
        """One local-model call for the semantic fields. Never fatal."""
        from app.services.local_llm import LocalLLMService

        excerpt = self._excerpt(pages)
        prompt = (
            "You are reading a company's website to describe the business plainly.\n"
            f"Domain: {project.domain}\n\n"
            f"Page titles and descriptions:\n{excerpt}\n\n"
            "Describe only what the pages support. If something is not clear from "
            "them, use null rather than guessing."
        )
        schema = json.dumps(
            {
                "business_type": "short label, e.g. 'Dental clinic' or 'B2B SaaS', or null",
                "niche": "the specific area within that, or null",
                "target_audience": "who the site is written for, or null",
                "confidence": "0.0 to 1.0, how clearly the pages supported this",
            }
        )

        try:
            result = await LocalLLMService().generate_json(prompt=prompt, schema_hint=schema)
        except Exception as exc:
            # The profile is still useful without this pass; extraction already
            # produced most of it. Content work is never blocked on the model.
            logger.warning("profile_inference_failed", project_id=str(project.id), error=str(exc))
            return {}

        payload = result.get("json") or {}
        if not isinstance(payload, dict):
            return {}

        confidence = payload.get("confidence")
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            key: payload.get(key)
            for key in missing
            if isinstance(payload.get(key), str) and payload.get(key).strip()
        } | {"_confidence": confidence}

    def _excerpt(self, pages: Sequence[CrawlPage], limit: int = 25) -> str:
        lines = []
        for page in pages[:limit]:
            title = (page.title or "").strip()
            desc = (page.meta_description or "").strip()
            if title or desc:
                lines.append(f"- {title} :: {desc}"[:300])
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        project: Project,
        tenant_id: UUID,
        existing: Optional[WebsiteProfile],
        extracted: Dict[str, Any],
        inferred: Dict[str, Any],
        content_hash: str,
        used_llm: str,
        pages: Sequence[CrawlPage],
    ) -> WebsiteProfile:
        confidence = float(inferred.pop("_confidence", 0.0) or 0.0)
        profile = existing or WebsiteProfile(
            tenant_id=tenant_id, project_id=project.id, version=0
        )

        if existing is not None:
            await self._snapshot(existing)

        sources: Dict[str, str] = {}
        confidences: Dict[str, float] = {}
        evidence: Dict[str, str] = {}
        page_evidence = ", ".join(
            sorted({item["role"] for item in (extracted.get("important_pages") or [])})
        ) or "crawled pages"

        def assign(field: str, value: Any, source: str, conf: Optional[float] = None, why: str = "") -> None:
            setattr(profile, field, value)
            sources[field] = source
            if conf is not None:
                confidences[field] = round(conf, 2)
            if why:
                evidence[field] = why

        # 1. Anything the owner stated wins outright.
        for field, project_attr in USER_FIELD_MAP.items():
            stated = getattr(project, project_attr, None)
            if stated:
                assign(field, stated, ProfileFieldSource.user.value, why="Provided in the project brief")

        # 2. Deterministic extraction fills what is still blank.
        for field in (
            "business_name", "description", "services", "products", "locations",
            "primary_topics", "brand_terms", "industry", "target_audience",
        ):
            if sources.get(field) == ProfileFieldSource.user.value:
                continue
            value = extracted.get(field)
            if value:
                assign(field, value, ProfileFieldSource.inferred.value, 0.9,
                       f"Read directly from {page_evidence}")
            elif getattr(profile, field, None) in (None, [], ""):
                assign(field, [] if field in ("services", "products", "locations",
                                              "primary_topics", "brand_terms") else None,
                       ProfileFieldSource.unknown.value)

        # 3. The model only answers what the first two passes left blank.
        for field in ("business_type", "niche", "target_audience"):
            if sources.get(field) in (ProfileFieldSource.user.value,):
                continue
            value = inferred.get(field)
            if value:
                assign(field, value, ProfileFieldSource.inferred.value, confidence,
                       f"Inferred by the local model from {page_evidence}")
            elif sources.get(field) is None:
                assign(field, getattr(profile, field, None), ProfileFieldSource.unknown.value)

        profile.important_pages = extracted.get("important_pages") or []
        profile.field_sources = sources
        profile.field_confidence = confidences
        profile.field_evidence = evidence
        profile.confidence = round(
            sum(confidences.values()) / len(confidences), 2
        ) if confidences else 0.0
        profile.used_llm = used_llm
        profile.content_hash = content_hash
        profile.status = WebsiteProfileStatus.completed
        profile.version = int(profile.version or 0) + 1
        profile.generated_at = datetime.utcnow()
        profile.error = None

        if existing is None:
            self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)

        logger.info(
            "website_profile_built",
            project_id=str(project.id),
            version=profile.version,
            used_llm=used_llm,
            pages=len(pages),
        )
        return profile

    async def _snapshot(self, profile: WebsiteProfile) -> None:
        """Keep the version being replaced, so a changed belief is auditable."""
        self.db.add(
            WebsiteProfileSnapshot(
                tenant_id=profile.tenant_id,
                project_id=profile.project_id,
                profile_id=profile.id,
                version=int(profile.version or 1),
                payload={
                    "business_type": profile.business_type,
                    "industry": profile.industry,
                    "niche": profile.niche,
                    "services": profile.services,
                    "primary_topics": profile.primary_topics,
                    "field_sources": profile.field_sources,
                    "confidence": profile.confidence,
                },
                change_summary=f"Replaced by version {int(profile.version or 1) + 1}.",
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def _pages(self, project_id: UUID, tenant_id: UUID) -> List[CrawlPage]:
        crawl = await latest_completed_crawl(self.db, project_id, tenant_id)
        if not crawl:
            return []
        result = await self.db.execute(
            select(CrawlPage)
            .where(CrawlPage.crawl_job_id == crawl.id)
            .order_by(CrawlPage.url)
            .limit(500)
        )
        return list(result.scalars().all())

    def _hash(self, pages: Sequence[CrawlPage]) -> str:
        """Identity of the content a profile was built from.

        Titles, descriptions and URLs only — body text changes on every build
        of a dynamic site (timestamps, counters) and would defeat the reuse this
        hash exists to enable.
        """
        digest = hashlib.sha256()
        for page in sorted(pages, key=lambda p: p.url or ""):
            digest.update((page.url or "").encode("utf-8", "ignore"))
            digest.update((page.title or "").encode("utf-8", "ignore"))
            digest.update((page.meta_description or "").encode("utf-8", "ignore"))
        return digest.hexdigest()

    def _brand_terms(self, titles: Sequence[str]) -> List[str]:
        """The phrase repeated across page titles is almost always the brand."""
        counter: Counter = Counter()
        for title in titles:
            parts = [p.strip() for p in re.split(r"[|\-–—]", title) if p.strip()]
            if len(parts) > 1:
                counter[parts[-1]] += 1
        return [term for term, count in counter.most_common(3) if count >= 2 and len(term) < 60]
