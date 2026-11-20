"""AI SEO Growth Engine — the growth strategist.

Where the rest of the platform fixes SEO, this engine continuously discovers ways
to GROW traffic: keyword opportunities (by intent), content gaps, topic clusters,
a framework-aware blog roadmap + content calendar, an EEAT assessment, and a
traffic forecast. It composes the project's real signals (project brief, Search
Console opportunities, keyword baselines, crawl, blog topics) with the technology
fingerprint so every recommendation stays framework-aware.

It only produces SEO recommendations and SEO-safe content plans — it never edits
UI, business logic, CRM, payments, auth, or the database beyond its own snapshot.
Traffic numbers are always ESTIMATES, clearly labelled, never fabricated as
measured.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.growth.analysis import (
    classify_intent,
    cluster_topics,
    estimate_traffic,
    growth_score,
    keyword_difficulty,
    priority_score,
    suggest_blog_post,
)
from app.models.growth_snapshot import GrowthSnapshot
from app.models.project import Project

logger = structlog.get_logger(__name__)


class SeoGrowthEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -- keyword discovery --------------------------------------------------

    async def keyword_opportunities(self, project_id: UUID, tenant_id: UUID, limit: int = 40) -> List[Dict[str, Any]]:
        project = await self._project(project_id, tenant_id)
        if not project:
            return []
        brand = [project.business_name] if project.business_name else []
        seen: set = set()
        out: List[Dict[str, Any]] = []

        # 1) REAL Search Console opportunities (high-impression / low-CTR, etc.)
        for opp in await self._gsc_opportunities(project_id, tenant_id):
            kw = (opp.get("query") or "").strip()
            if not kw or kw.lower() in seen:
                continue
            seen.add(kw.lower())
            intent = classify_intent(kw, brand)
            pos = opp.get("position")
            diff = keyword_difficulty(int(pos) if pos else None, None)
            out.append({
                "keyword": kw, "intent": intent, "difficulty": diff,
                "source": "search_console",
                "impressions": opp.get("impressions"), "ctr": opp.get("ctr"), "position": pos,
                "priority": priority_score(intent=intent, difficulty=diff, impressions=opp.get("impressions"),
                                           position=int(pos) if pos else None, ctr=opp.get("ctr")),
                "estimate": estimate_traffic(opp.get("impressions"), pos, opp.get("ctr")),
                "opportunity_type": opp.get("opportunity_type"),
            })

        # 2) Tracked keyword baselines (real positions).
        for kb in await self._baselines(project_id, tenant_id):
            kw = (kb.keyword or "").strip()
            if not kw or kw.lower() in seen:
                continue
            seen.add(kw.lower())
            intent = kb.intent or classify_intent(kw, brand)
            diff = keyword_difficulty(kb.current_position, kb.search_volume)
            out.append({
                "keyword": kw, "intent": intent, "difficulty": diff, "source": "baseline",
                "impressions": None, "ctr": None, "position": kb.current_position,
                "priority": priority_score(intent=intent, difficulty=diff, position=kb.current_position),
                "estimate": estimate_traffic(kb.search_volume, kb.current_position),
            })

        # 3) Seed keywords from the project brief (no external data required).
        seeds = list(project.target_keywords or []) + list(project.keywords or [])
        for s in project.primary_services or []:
            seeds.append(f"{s} {project.target_location}".strip() if project.target_location else s)
        for kw in seeds:
            kw = (kw or "").strip()
            if not kw or kw.lower() in seen:
                continue
            seen.add(kw.lower())
            intent = classify_intent(kw, brand)
            diff = keyword_difficulty(None, None)
            out.append({
                "keyword": kw, "intent": intent, "difficulty": diff, "source": "project_brief",
                "impressions": None, "ctr": None, "position": None,
                "priority": priority_score(intent=intent, difficulty=diff),
                "estimate": estimate_traffic(None, None),
            })

        out.sort(key=lambda o: o["priority"], reverse=True)
        return out[:limit]

    # -- content gaps -------------------------------------------------------

    async def content_gaps(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        project = await self._project(project_id, tenant_id)
        if not project:
            return []
        pages = await self._crawl_paths(project_id, tenant_id)
        page_blob = " ".join(pages).lower()
        gaps: List[Dict[str, Any]] = []

        # Missing service pages.
        for svc in project.primary_services or []:
            slug = svc.lower().replace(" ", "-")
            if slug not in page_blob and svc.lower() not in page_blob:
                gaps.append({"type": "service_page", "title": f"Service page: {svc}",
                             "why": f"You offer '{svc}' but no dedicated page was found — a focused page can rank for it.",
                             "target_keyword": svc, "priority": 78})

        # Missing city / local page.
        if project.target_location:
            loc = project.target_location.lower()
            if loc not in page_blob:
                gaps.append({"type": "city_page", "title": f"Local page: {project.target_location}",
                             "why": f"No page targets '{project.target_location}' — a local page captures near-me searches.",
                             "target_keyword": f"{(project.primary_services or ['services'])[0]} {project.target_location}",
                             "priority": 72})

        # Missing FAQ / comparison / guide content (topic types).
        for topic_type, kw_suffix, why in (
            ("faq_page", "faq", "FAQ content wins question keywords and can earn rich results."),
            ("comparison", "vs alternatives", "Comparison pages capture high-intent commercial searches."),
            ("guide", "guide", "In-depth guides build topical authority and long-tail traffic."),
        ):
            if topic_type.split("_")[0] not in page_blob:
                base = (project.primary_services or [project.industry or "services"])[0]
                gaps.append({"type": topic_type, "title": f"{topic_type.replace('_', ' ').title()}: {base}",
                             "why": why, "target_keyword": f"{base} {kw_suffix}".strip(), "priority": 60})

        # Blog topics already suggested but not yet covered.
        for t in await self._blog_topics(project_id, tenant_id):
            kw = (getattr(t, "target_keyword", "") or "").lower()
            if kw and kw not in page_blob:
                gaps.append({"type": "blog_topic", "title": getattr(t, "title", kw),
                             "why": "A planned topic that isn't published yet.",
                             "target_keyword": getattr(t, "target_keyword", ""), "priority": 55})

        # Competitor note (honest — we don't scrape competitors here).
        if project.competitor_urls:
            gaps.append({"type": "competitor_analysis",
                         "title": f"Analyze {len(project.competitor_urls)} competitor(s)",
                         "why": "Competitors are configured — a SERP/content comparison can reveal topics they rank for that you don't.",
                         "target_keyword": None, "priority": 50})

        gaps.sort(key=lambda g: g["priority"], reverse=True)
        return gaps

    # -- topic clusters + roadmap + calendar --------------------------------

    async def topic_clusters(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        kws = [o["keyword"] for o in await self.keyword_opportunities(project_id, tenant_id, limit=60)]
        return cluster_topics(kws)

    async def blog_roadmap(self, project_id: UUID, tenant_id: UUID, limit: int = 12) -> List[Dict[str, Any]]:
        project = await self._project(project_id, tenant_id)
        if not project:
            return []
        framework_key = await self._framework_key(project_id, tenant_id)
        domain = project.domain or ""
        opps = await self.keyword_opportunities(project_id, tenant_id, limit=40)
        gaps = await self.content_gaps(project_id, tenant_id)

        roadmap: List[Dict[str, Any]] = []
        # From gaps first (highest strategic value), then keyword opportunities.
        for g in gaps:
            if g["type"] in ("competitor_analysis",):
                continue
            kw = g.get("target_keyword") or g["title"]
            post = suggest_blog_post(g["title"], kw, framework_key=framework_key, domain=domain,
                                     secondary=self._secondary_for(kw, opps))
            post.update({"priority": g["priority"], "difficulty": "medium", "source": "content_gap",
                         "estimated_traffic": None, "business_value": "high" if g["priority"] >= 70 else "medium"})
            roadmap.append(post)

        for o in opps:
            if o["intent"] in ("navigational", "brand"):
                continue
            title = f"{o['keyword'].title()}"
            post = suggest_blog_post(title, o["keyword"], framework_key=framework_key, domain=domain,
                                     secondary=self._secondary_for(o["keyword"], opps))
            post.update({"priority": o["priority"], "difficulty": o["difficulty"], "source": o["source"],
                         "estimated_traffic": o["estimate"].get("estimated_monthly_clicks"),
                         "business_value": "high" if o["intent"] in ("transactional", "commercial", "local") else "medium"})
            roadmap.append(post)

        # dedupe by url, sort by priority
        seen, unique = set(), []
        for p in sorted(roadmap, key=lambda x: x["priority"], reverse=True):
            if p["suggested_url"] in seen:
                continue
            seen.add(p["suggested_url"])
            unique.append(p)
        return unique[:limit]

    async def content_calendar(self, project_id: UUID, tenant_id: UUID, days: int = 90) -> Dict[str, Any]:
        roadmap = await self.blog_roadmap(project_id, tenant_id, limit=24)
        # ~2 posts / week cadence.
        cadence_days = 3
        start = datetime.utcnow().date()
        slots = []
        for i, post in enumerate(roadmap):
            when = start + timedelta(days=cadence_days * (i + 1))
            if (when - start).days > days:
                break
            slots.append({"publish_date": when.isoformat(), "title": post["suggested_title"],
                          "target_keyword": post["target_keyword"], "url": post["suggested_url"],
                          "priority": post["priority"], "business_value": post.get("business_value")})
        return {"window_days": days, "cadence": "~2 posts / week", "slots": slots, "planned": len(slots)}

    # -- EEAT + forecast + score -------------------------------------------

    async def eeat(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        pages = " ".join(await self._crawl_paths(project_id, tenant_id)).lower()
        fp = await self._fingerprint(project_id, tenant_id)
        has_schema = any("json-ld" in (t.get("name") or "").lower() for t in fp.get("technologies", []))
        checks = {
            "about_page": "about" in pages,
            "contact_page": "contact" in pages,
            "author_pages": "author" in pages or "team" in pages or "/staff" in pages,
            "organization_schema": has_schema,
            "trust_signals": any(k in pages for k in ("privacy", "terms", "policy")),
        }
        present = sum(1 for v in checks.values() if v)
        score = int(round(100 * present / len(checks)))
        suggestions = []
        if not checks["about_page"]:
            suggestions.append("Add a detailed About page describing the organization and expertise.")
        if not checks["author_pages"]:
            suggestions.append("Add author/team pages with credentials to strengthen Experience & Expertise.")
        if not checks["organization_schema"]:
            suggestions.append("Add Organization JSON-LD schema to reinforce entity trust.")
        if not checks["trust_signals"]:
            suggestions.append("Add privacy/terms and, where relevant, medical/legal/business disclaimers.")
        industry = (await self._project(project_id, tenant_id)).industry or ""
        if any(k in industry.lower() for k in ("health", "medical", "finance", "legal", "law")):
            suggestions.append("YMYL industry: add references, citations and professional credentials for E-E-A-T.")
        return {"score": score, "checks": checks, "suggestions": suggestions}

    async def traffic_forecast(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        opps = await self.keyword_opportunities(project_id, tenant_id, limit=40)
        est = [o["estimate"].get("estimated_monthly_clicks") for o in opps
               if o["estimate"].get("estimated_monthly_clicks")]
        total = sum(est) if est else None
        with_data = len(est)
        return {
            "is_estimate": True,
            "estimated_monthly_clicks": total,
            "keywords_with_data": with_data,
            "keyword_opportunities": len(opps),
            "confidence": "low" if with_data == 0 else "medium" if with_data < 10 else "high",
            "note": "Estimate only, based on current impressions/CTR where available. Connect Search Console for a stronger forecast; never treated as measured.",
        }

    async def growth_score(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        opps = await self.keyword_opportunities(project_id, tenant_id, limit=60)
        gaps = await self.content_gaps(project_id, tenant_id)
        clusters = cluster_topics([o["keyword"] for o in opps])
        eeat = await self.eeat(project_id, tenant_id)
        pages = await self._crawl_paths(project_id, tenant_id)

        # keyword coverage: how many opportunities already rank in the top 20.
        ranking = [o for o in opps if o.get("position") and o["position"] <= 20]
        keyword_coverage = int(round(100 * len(ranking) / len(opps))) if opps else None
        # topic coverage: clusters that have at least one existing page.
        page_blob = " ".join(pages).lower()
        covered = sum(1 for c in clusters if c["pillar"] in page_blob)
        topic_coverage = int(round(100 * covered / len(clusters))) if clusters else None
        # content authority = EEAT.
        content_authority = eeat["score"]
        # content pipeline: gaps being addressed (inverse of open gaps, capped).
        content_pipeline = max(20, 100 - len(gaps) * 6) if gaps is not None else None
        # opportunity score (potential): more high-priority opportunities = more room to grow.
        high = [o for o in opps if o["priority"] >= 70]
        opportunity_score = min(100, 30 + len(high) * 8) if opps else None

        dims = {
            "keyword_coverage": keyword_coverage,
            "topic_coverage": topic_coverage,
            "content_authority": content_authority,
            "content_pipeline": content_pipeline,
        }
        gs = growth_score(dims)
        gs["opportunity_score"] = opportunity_score
        gs["explanations"] = {
            "keyword_coverage": "Share of target keywords already ranking in the top 20.",
            "topic_coverage": "Share of topic clusters that have at least one existing page.",
            "content_authority": "E-E-A-T signals (About/author/contact/schema/trust pages).",
            "content_pipeline": "How few content gaps remain open (higher = fewer gaps).",
            "opportunity_score": "Growth headroom — the number of high-priority keyword opportunities available.",
        }
        return gs

    # -- analyze / persist / summaries -------------------------------------

    async def analyze(self, project_id: UUID, tenant_id: UUID) -> GrowthSnapshot:
        if not await self._project(project_id, tenant_id):
            raise ValueError("Project not found")
        opps = await self.keyword_opportunities(project_id, tenant_id)
        gaps = await self.content_gaps(project_id, tenant_id)
        clusters = await self.topic_clusters(project_id, tenant_id)
        roadmap = await self.blog_roadmap(project_id, tenant_id)
        forecast = await self.traffic_forecast(project_id, tenant_id)
        eeat = await self.eeat(project_id, tenant_id)
        gs = await self.growth_score(project_id, tenant_id)

        snap = GrowthSnapshot(
            tenant_id=tenant_id, project_id=project_id,
            growth_score=gs.get("overall"),
            dimensions={**gs.get("dimensions", {}), "opportunity_score": gs.get("opportunity_score")},
            keyword_opportunities=opps, content_gaps=gaps, topic_clusters=clusters,
            blog_roadmap=roadmap, traffic_forecast=forecast, eeat=eeat,
        )
        self.db.add(snap)
        await self.db.commit()
        await self.db.refresh(snap)
        logger.info("growth_analyzed", project_id=str(project_id), score=snap.growth_score,
                    opportunities=len(opps), gaps=len(gaps))
        return snap

    async def summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        gs = await self.growth_score(project_id, tenant_id)
        forecast = await self.traffic_forecast(project_id, tenant_id)
        opps = await self.keyword_opportunities(project_id, tenant_id, limit=10)
        gaps = await self.content_gaps(project_id, tenant_id)
        return {
            "growth_score": gs.get("overall"),
            "dimensions": gs.get("dimensions"),
            "opportunity_score": gs.get("opportunity_score"),
            "explanations": gs.get("explanations"),
            "top_keywords": opps[:8],
            "content_gaps": gaps[:8],
            "traffic_forecast": forecast,
        }

    async def mission_control_summary(self, tenant_id: UUID) -> Dict[str, Any]:
        projects = (await self.db.execute(
            select(Project).where(Project.tenant_id == tenant_id, Project.is_active.is_(True))
        )).scalars().all()
        scores, opp_counts, est_total = [], 0, 0
        for p in projects:
            try:
                gs = await self.growth_score(p.id, tenant_id)
                if gs.get("overall") is not None:
                    scores.append(gs["overall"])
                fc = await self.traffic_forecast(p.id, tenant_id)
                opp_counts += fc.get("keyword_opportunities", 0)
                est_total += fc.get("estimated_monthly_clicks") or 0
            except Exception:
                continue
        return {
            "average_growth_score": int(round(sum(scores) / len(scores))) if scores else None,
            "keyword_opportunities": opp_counts,
            "estimated_monthly_clicks": est_total or None,
            "projects": len(projects),
            "is_estimate": True,
        }

    async def briefing_summary(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        opps = await self.keyword_opportunities(project_id, tenant_id, limit=10)
        gaps = await self.content_gaps(project_id, tenant_id)
        roadmap = await self.blog_roadmap(project_id, tenant_id, limit=5)
        return {
            "new_opportunities": len(opps),
            "priority_keywords": [{"keyword": o["keyword"], "intent": o["intent"], "priority": o["priority"]} for o in opps[:5]],
            "missing_topics": [g["title"] for g in gaps[:5]],
            "recommended_blogs": [{"title": p["suggested_title"], "target_keyword": p["target_keyword"]} for p in roadmap],
        }

    # -- data helpers -------------------------------------------------------

    async def _project(self, project_id, tenant_id) -> Optional[Project]:
        return (await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )).scalars().first()

    async def _gsc_opportunities(self, project_id, tenant_id) -> List[Dict[str, Any]]:
        try:
            from app.models.search_console import SearchConsoleOpportunity
            rows = (await self.db.execute(
                select(SearchConsoleOpportunity).where(
                    SearchConsoleOpportunity.project_id == project_id,
                    SearchConsoleOpportunity.tenant_id == tenant_id,
                ).limit(60)
            )).scalars().all()
            return [{"query": r.query, "impressions": r.current_impressions, "clicks": r.current_clicks,
                     "ctr": r.current_ctr, "position": r.current_position,
                     "opportunity_type": getattr(r.opportunity_type, "value", r.opportunity_type)} for r in rows]
        except Exception:
            return []

    async def _baselines(self, project_id, tenant_id):
        try:
            from app.models.keyword_baseline import KeywordBaseline
            return (await self.db.execute(
                select(KeywordBaseline).where(
                    KeywordBaseline.project_id == project_id, KeywordBaseline.tenant_id == tenant_id
                ).limit(60)
            )).scalars().all()
        except Exception:
            return []

    async def _blog_topics(self, project_id, tenant_id):
        try:
            from app.models.blog import BlogTopic
            return (await self.db.execute(
                select(BlogTopic).where(
                    BlogTopic.project_id == project_id, BlogTopic.tenant_id == tenant_id
                ).limit(40)
            )).scalars().all()
        except Exception:
            return []

    async def _crawl_paths(self, project_id, tenant_id) -> List[str]:
        try:
            from app.models.crawl import CrawlJob, CrawlPage, CrawlStatus
            job = (await self.db.execute(
                select(CrawlJob).where(CrawlJob.project_id == project_id, CrawlJob.status == CrawlStatus.completed)
                .order_by(CrawlJob.created_at.desc()).limit(1)
            )).scalars().first()
            if not job:
                return []
            pages = (await self.db.execute(
                select(CrawlPage).where(CrawlPage.crawl_job_id == job.id).limit(500)
            )).scalars().all()
            out = []
            for p in pages:
                url = getattr(p, "normalized_url", None) or getattr(p, "url", "")
                out.append(urlparse(url).path if "://" in url else url)
            return out
        except Exception:
            return []

    async def _fingerprint(self, project_id, tenant_id) -> Dict[str, Any]:
        try:
            from app.services.fingerprint import FingerprintService
            return await FingerprintService(self.db).summary(project_id, tenant_id)
        except Exception:
            return {}

    async def _framework_key(self, project_id, tenant_id) -> Optional[str]:
        fp = await self._fingerprint(project_id, tenant_id)
        return (fp.get("strategy") or {}).get("primary_framework_key")

    @staticmethod
    def _secondary_for(keyword: str, opps: List[Dict[str, Any]]) -> List[str]:
        base = (keyword or "").lower().split()
        out = []
        for o in opps:
            k = o["keyword"]
            if k.lower() != (keyword or "").lower() and any(w in k.lower() for w in base if len(w) > 3):
                out.append(k)
        return out[:5]
