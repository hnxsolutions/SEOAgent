"""The autonomous content loop: find topics, draft one, measure what shipped.

This service **composes** what the project already has rather than adding a
second content system beside it:

* `BlogPlan` / `BlogTopic` / `BlogDraft` and `BlogService` keep owning plans,
  topic records and LLM drafting.
* `SeoGrowthEngine` keeps owning content gaps and clustering.
* Search Console rows that are already synced are the demand signal.
* `app/content_engine/scoring.py` holds the ranking rules, as pure functions.

What is new is only the part that was missing: a weekly job that turns free,
first-party signals into ranked topics; a drafting slot that writes **at most
one** article and refuses to write a bad one; and a weekly review that measures
what was published and proposes updates.

Three rules it will not break:

**No invented numbers.** Search volume stays `None` everywhere. Topics carry an
Opportunity Score built from measured impressions, clicks, CTR and position.
A project with no Search Console connection gets topics from its own content
gaps, clearly marked as having no demand evidence — not a guessed volume.

**Skipping is a valid outcome.** A drafting slot with nothing worth writing
records why and stops. Filling a schedule is not the goal.

**Nothing publishes itself.** Everything this produces is a proposal; the
existing human approval workflow remains the only path to publication.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_engine.scoring import (
    CannibalMatch,
    OpportunitySignals,
    SCORE_WEIGHTS,
    business_relevance,
    classify_performance,
    find_cannibalisation,
    normalise_phrase,
    score_opportunity,
)
from app.models.blog import (
    BlogDraft,
    BlogDraftStatus,
    BlogPlan,
    BlogPlanStatus,
    BlogSearchIntent,
    BlogTopic,
    BlogTopicStatus,
)
from app.models.crawl import CrawlJob, CrawlPage, CrawlStatus
from app.models.project import Project
from app.models.search_console import SearchConsoleRow

logger = structlog.get_logger(__name__)


#: Topics below this score are not worth an article. The drafting slot skips
#: rather than writing something nobody searched for.
MIN_TOPIC_SCORE = 25

#: How many candidates one scan keeps. More than this and the approval queue
#: becomes a thing nobody reads.
MAX_TOPICS_PER_SCAN = 15

#: Search Console lookback for demand signals.
DEMAND_WINDOW_DAYS = 90


async def latest_completed_crawl(
    db: AsyncSession, project_id: UUID, tenant_id: UUID
) -> Optional[CrawlJob]:
    """The most recent finished crawl, or None. Shared with the scheduler."""
    result = await db.execute(
        select(CrawlJob)
        .where(
            CrawlJob.project_id == project_id,
            CrawlJob.tenant_id == tenant_id,
            CrawlJob.status == CrawlStatus.completed,
        )
        .order_by(CrawlJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


class ContentEngineService:
    """Opportunity scanning, drafting and performance review for one project."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # 1. Find what is worth writing
    # ------------------------------------------------------------------

    async def scan_opportunities(
        self, project_id: UUID, tenant_id: UUID, *, limit: int = MAX_TOPICS_PER_SCAN
    ) -> Dict[str, Any]:
        """Rank free signals into topics and persist the new ones.

        Returns a summary rather than the rows: this is called from a scheduled
        job whose record should stay small and readable.
        """
        project = await self._project(project_id, tenant_id)
        if not project:
            return {"status": "skipped", "reason": "Project not found.", "topics_created": 0}

        plan = await self._ensure_plan(project, tenant_id)
        existing = await self._existing_topics(plan.id, tenant_id)
        covered = await self._covered_phrases(project_id, tenant_id)
        value_terms = self._business_terms(project)

        candidates = await self._demand_candidates(project_id, tenant_id)
        demand_source = "search_console" if candidates else "content_gaps"
        if not candidates:
            candidates = await self._gap_candidates(project_id, tenant_id)

        scored: List[Tuple[int, Dict[str, Any]]] = []
        duplicates = 0

        for candidate in candidates:
            query = candidate["query"]
            if not normalise_phrase(query):
                continue

            clash = find_cannibalisation(query, existing)
            if clash is not None:
                duplicates += 1
                continue

            signals = OpportunitySignals(
                query=query,
                impressions=int(candidate.get("impressions") or 0),
                clicks=int(candidate.get("clicks") or 0),
                ctr=candidate.get("ctr"),
                position=candidate.get("position"),
                has_covering_page=self._is_covered(query, covered),
                business_relevance=business_relevance(query, value_terms),
            )
            result = score_opportunity(signals)
            if result.score < MIN_TOPIC_SCORE:
                continue

            scored.append((result.score, {
                "query": query,
                "score": result.score,
                "breakdown": result.breakdown,
                "reasons": result.reasons,
                "position": signals.position,
                "impressions": signals.impressions,
                "covered": signals.has_covering_page,
                "page_url": candidate.get("page_url"),
            }))

        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = [item[1] for item in scored[:limit]]

        created = 0
        for item in chosen:
            self.db.add(self._topic_record(plan, project, tenant_id, item))
            created += 1
            existing.append((item["query"], None))

        if created:
            plan.status = BlogPlanStatus.active
        await self.db.commit()

        logger.info(
            "content_opportunities_scanned",
            project_id=str(project_id),
            demand_source=demand_source,
            candidates=len(candidates),
            topics_created=created,
            duplicates_skipped=duplicates,
        )
        return {
            "status": "completed",
            "plan_id": str(plan.id),
            "demand_source": demand_source,
            "candidates_considered": len(candidates),
            "topics_created": created,
            "duplicates_skipped": duplicates,
            "scoring_formula": SCORE_WEIGHTS,
            "note": (
                "Opportunity Score only — no search volume is available without a paid "
                "provider and none is estimated."
            ),
        }

    # ------------------------------------------------------------------
    # 2. Write at most one article
    # ------------------------------------------------------------------

    async def draft_next(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Draft the highest-scoring unwritten topic, or explain the skip."""
        project = await self._project(project_id, tenant_id)
        if not project:
            return {"drafted": False, "reason": "Project not found."}

        plan = await self._active_plan(project_id, tenant_id)
        if not plan:
            return {"drafted": False, "reason": "No content plan yet — the opportunity scan has not run."}

        topic = await self._next_topic(plan.id, tenant_id)
        if not topic:
            return {
                "drafted": False,
                "reason": (
                    "No topic above the quality bar is waiting. Skipping this slot rather "
                    "than drafting something not worth publishing."
                ),
            }

        # Re-check cannibalisation at drafting time: a topic queued last week may
        # have been covered by an article written since.
        published = await self._published_titles(project_id, tenant_id)
        clash = find_cannibalisation(topic.title, published)
        if clash is not None:
            topic.status = BlogTopicStatus.rejected
            topic.reason = (
                f"Skipped — \"{clash.existing}\" already covers this intent "
                f"({clash.overlap:.0%} overlap). Update that article instead."
            )
            await self.db.commit()
            return {
                "drafted": False,
                "reason": topic.reason,
                "cannibalised_by": clash.existing,
            }

        from app.services.blogs import BlogService

        try:
            draft = await BlogService(self.db).draft_topic(topic.id, tenant_id)
        except Exception as exc:
            # A model that is down must leave the topic draftable next slot,
            # never consume it. See PART 28 — fail safely.
            logger.warning(
                "blog_draft_failed", project_id=str(project_id), topic_id=str(topic.id), error=str(exc)
            )
            return {
                "drafted": False,
                "reason": f"Drafting is unavailable right now ({type(exc).__name__}). The topic stays queued.",
            }

        validation = await self.validate_draft(draft.id, tenant_id)
        return {
            "drafted": True,
            "draft_id": str(draft.id),
            "topic_id": str(topic.id),
            "title": draft.title,
            "opportunity_score": float(topic.priority_score or 0),
            "seo_score": validation.get("seo_score"),
            "aeo_score": validation.get("aeo_score"),
            "status": "pending_approval",
        }

    # ------------------------------------------------------------------
    # 3. Validate what was written
    # ------------------------------------------------------------------

    async def validate_draft(self, draft_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Score a draft for SEO and answer-engine readiness.

        Deterministic checks over the draft's own fields — no model call, so
        validation costs nothing and cannot itself hallucinate a pass.
        """
        draft = await self.db.get(BlogDraft, draft_id)
        if not draft or draft.tenant_id != tenant_id:
            return {"seo_score": None, "aeo_score": None, "issues": ["Draft not found."]}

        body = draft.draft_markdown or ""
        words = len(body.split())
        headings = [line for line in body.splitlines() if line.startswith("#")]
        h2s = [line for line in headings if line.startswith("## ")]

        # Weighted, not counted. A flat penalty per issue let a ten-word article
        # with one heading score 72 and "pass", because it could only ever fail
        # two checks. Thin content and a missing title are disqualifying; a meta
        # description five characters too long is not.
        seo: List[Tuple[str, int]] = []
        if not draft.meta_title:
            seo.append(("No meta title.", 25))
        elif len(draft.meta_title) > 60:
            seo.append((f"Meta title is {len(draft.meta_title)} characters — over 60 risks truncation.", 8))
        if not draft.meta_description:
            seo.append(("No meta description.", 15))
        elif not 70 <= len(draft.meta_description) <= 160:
            seo.append((f"Meta description is {len(draft.meta_description)} characters — aim for 70-160.", 8))
        if words < 300:
            seo.append((f"Only {words} words — far too thin to rank for anything.", 50))
        elif words < 600:
            seo.append((f"Only {words} words — thin for a ranking article.", 20))
        if len(h2s) < 2:
            seo.append((f"Only {len(h2s)} H2 sections — this is not a structured article.", 30))
        elif len(h2s) < 4:
            seo.append((f"Only {len(h2s)} H2 sections — too flat to cover a topic properly.", 10))
        if not draft.internal_link_plan:
            seo.append(("No internal links planned.", 12))
        if not draft.slug:
            seo.append(("No URL slug.", 20))

        aeo: List[Tuple[str, int]] = []
        if not draft.faq_json:
            aeo.append(("No FAQ block — answer engines lift these directly.", 25))
        if not draft.schema_json:
            aeo.append(("No structured data.", 25))
        if not body.strip():
            aeo.append(("Empty body — nothing to extract.", 50))
        elif not body.strip().splitlines()[0].strip():
            aeo.append(("No opening answer — the first paragraph should answer the question asked.", 20))
        if not [h for h in h2s if "?" in h]:
            aeo.append(("No question-shaped headings — these are what gets quoted.", 15))

        seo_score = max(0, 100 - sum(weight for _, weight in seo))
        aeo_score = max(0, 100 - sum(weight for _, weight in aeo))

        return {
            "draft_id": str(draft_id),
            "seo_score": seo_score,
            "aeo_score": aeo_score,
            "word_count": words,
            "heading_count": len(h2s),
            "seo_issues": [issue for issue, _ in seo],
            "aeo_issues": [issue for issue, _ in aeo],
            "passed": seo_score >= 70 and aeo_score >= 60,
        }

    # ------------------------------------------------------------------
    # 4. Measure what shipped
    # ------------------------------------------------------------------

    async def review_performance(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Classify published articles from Search Console, honestly.

        Articles with too little data are labelled `NO_DATA_YET` rather than
        judged. Where an article has genuinely declined, a refresh proposal is
        described — never applied.
        """
        published = await self._published_drafts(project_id, tenant_id)
        if not published:
            return {"status": "completed", "articles": 0, "note": "Nothing published yet."}

        now = datetime.utcnow()
        current = await self._gsc_by_page(project_id, tenant_id, days=28)
        previous = await self._gsc_by_page(project_id, tenant_id, days=56, offset_days=28)

        buckets: Dict[str, int] = {}
        proposals: List[Dict[str, Any]] = []
        measured = 0

        for draft in published:
            key = (draft.slug or "").strip("/").lower()
            stats = current.get(key)
            if stats is None:
                buckets["NO_DATA_YET"] = buckets.get("NO_DATA_YET", 0) + 1
                continue

            measured += 1
            prior = previous.get(key) or {}
            days_live = (now - draft.published_at).days if draft.published_at else None

            label, why = classify_performance(
                impressions=int(stats.get("impressions") or 0),
                clicks=int(stats.get("clicks") or 0),
                position=stats.get("position"),
                previous_impressions=int(prior.get("impressions") or 0) or None,
                days_since_published=days_live,
            )
            buckets[label] = buckets.get(label, 0) + 1

            if label in ("NEEDS_UPDATE", "UNDERPERFORMING"):
                proposals.append({
                    "draft_id": str(draft.id),
                    "title": draft.title,
                    "slug": draft.slug,
                    "classification": label,
                    "reason": why,
                    "impressions": int(stats.get("impressions") or 0),
                    "clicks": int(stats.get("clicks") or 0),
                    "position": stats.get("position"),
                    "action": (
                        "Refresh proposal — requires approval. Nothing has been changed."
                    ),
                })

        return {
            "status": "completed",
            "articles": len(published),
            "measured": measured,
            "classifications": buckets,
            "refresh_proposals": proposals[:20],
            "note": (
                "Measured from Search Console only. Articles without enough data are "
                "reported as NO_DATA_YET rather than judged."
                if measured
                else "No Search Console data for these URLs yet."
            ),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def _ensure_plan(self, project: Project, tenant_id: UUID) -> BlogPlan:
        """One content plan per project, created on first scan."""
        existing = await self._active_plan(project.id, tenant_id)
        if existing:
            return existing

        from app.core.config import settings

        plan = BlogPlan(
            tenant_id=tenant_id,
            project_id=project.id,
            title=f"{project.name} content plan",
            description="Created automatically from free first-party signals.",
            target_site_url=project.domain,
            status=BlogPlanStatus.active,
            blogs_per_week=int(getattr(settings, "DEFAULT_BLOGS_PER_WEEK", 2)),
        )
        self.db.add(plan)
        await self.db.flush()
        return plan

    async def _active_plan(self, project_id: UUID, tenant_id: UUID) -> Optional[BlogPlan]:
        result = await self.db.execute(
            select(BlogPlan)
            .where(BlogPlan.project_id == project_id, BlogPlan.tenant_id == tenant_id)
            .order_by(BlogPlan.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _existing_topics(self, plan_id: UUID, tenant_id: UUID) -> List[Tuple[str, Optional[str]]]:
        result = await self.db.execute(
            select(BlogTopic.title, BlogTopic.target_keyword).where(
                BlogTopic.blog_plan_id == plan_id, BlogTopic.tenant_id == tenant_id
            )
        )
        pairs: List[Tuple[str, Optional[str]]] = []
        for title, keyword in result.all():
            pairs.append((title or "", None))
            if keyword and keyword != title:
                pairs.append((keyword, None))
        return pairs

    async def _published_titles(self, project_id: UUID, tenant_id: UUID) -> List[Tuple[str, Optional[str]]]:
        result = await self.db.execute(
            select(BlogDraft.title, BlogDraft.slug).where(
                BlogDraft.project_id == project_id,
                BlogDraft.tenant_id == tenant_id,
                BlogDraft.status == BlogDraftStatus.published,
            )
        )
        return [(title or "", slug) for title, slug in result.all()]

    async def _published_drafts(self, project_id: UUID, tenant_id: UUID) -> List[BlogDraft]:
        result = await self.db.execute(
            select(BlogDraft).where(
                BlogDraft.project_id == project_id,
                BlogDraft.tenant_id == tenant_id,
                BlogDraft.status == BlogDraftStatus.published,
            )
        )
        return list(result.scalars().all())

    async def _next_topic(self, plan_id: UUID, tenant_id: UUID) -> Optional[BlogTopic]:
        """The best topic still waiting, approved ones first.

        An approved topic outranks a merely suggested one of the same score
        because somebody has already said they want it written.
        """
        result = await self.db.execute(
            select(BlogTopic)
            .where(
                BlogTopic.blog_plan_id == plan_id,
                BlogTopic.tenant_id == tenant_id,
                BlogTopic.status.in_([BlogTopicStatus.approved, BlogTopicStatus.suggested]),
                BlogTopic.priority_score >= MIN_TOPIC_SCORE,
            )
            .order_by(BlogTopic.status.desc(), BlogTopic.priority_score.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _covered_phrases(self, project_id: UUID, tenant_id: UUID) -> List[str]:
        """Titles and URLs of pages that already exist on the site."""
        crawl = await latest_completed_crawl(self.db, project_id, tenant_id)
        if not crawl:
            return []
        result = await self.db.execute(
            select(CrawlPage.title, CrawlPage.url)
            .where(CrawlPage.crawl_job_id == crawl.id)
            .limit(2000)
        )
        phrases: List[str] = []
        for title, url in result.all():
            if title:
                phrases.append(title)
            if url:
                phrases.append(url.rsplit("/", 1)[-1].replace("-", " "))
        return phrases

    def _is_covered(self, query: str, covered: Sequence[str]) -> bool:
        return find_cannibalisation(query, [(phrase, None) for phrase in covered]) is not None

    def _business_terms(self, project: Project) -> List[str]:
        terms: List[str] = []
        for attribute in ("primary_services", "target_keywords", "keywords"):
            value = getattr(project, attribute, None)
            if isinstance(value, list):
                terms.extend(str(item) for item in value if item)
        for attribute in ("industry", "target_location", "business_name"):
            value = getattr(project, attribute, None)
            if value:
                terms.append(str(value))
        return terms

    async def _demand_candidates(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        """Search Console queries — the only real demand signal available free."""
        since = datetime.utcnow() - timedelta(days=DEMAND_WINDOW_DAYS)
        result = await self.db.execute(
            select(
                SearchConsoleRow.query,
                SearchConsoleRow.page_url,
                SearchConsoleRow.clicks,
                SearchConsoleRow.impressions,
                SearchConsoleRow.ctr,
                SearchConsoleRow.position,
            )
            .where(
                SearchConsoleRow.project_id == project_id,
                SearchConsoleRow.tenant_id == tenant_id,
                SearchConsoleRow.date_start >= since,
            )
            .order_by(SearchConsoleRow.impressions.desc())
            .limit(500)
        )

        merged: Dict[str, Dict[str, Any]] = {}
        for query, page_url, clicks, impressions, ctr, position in result.all():
            key = normalise_phrase(query or "")
            if not key:
                continue
            row = merged.setdefault(key, {
                "query": query, "page_url": page_url,
                "clicks": 0, "impressions": 0, "ctr": None, "position": None,
            })
            row["clicks"] += int(clicks or 0)
            row["impressions"] += int(impressions or 0)
            # Keep the best-ranking page's position for the phrase.
            if position and (row["position"] is None or position < row["position"]):
                row["position"] = float(position)
                row["page_url"] = page_url
        for row in merged.values():
            if row["impressions"]:
                row["ctr"] = row["clicks"] / row["impressions"]
        return list(merged.values())

    async def _gap_candidates(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        """Fallback when no Search Console data exists: the project's own gaps.

        These carry no impressions, so they score low on demand and high on
        coverage — which is the honest shape of "we think this is missing but
        nobody has measured anyone searching for it".
        """
        from app.services.seo_growth import SeoGrowthEngine

        try:
            gaps = await SeoGrowthEngine(self.db).content_gaps(project_id, tenant_id)
        except Exception as exc:
            logger.warning("content_gap_lookup_failed", project_id=str(project_id), error=str(exc))
            return []
        candidates: List[Dict[str, Any]] = []
        for gap in gaps or []:
            label = gap.get("topic") or gap.get("title") or gap.get("keyword")
            if label:
                candidates.append({"query": str(label), "impressions": 0, "clicks": 0})
        return candidates

    def _topic_record(
        self,
        plan: BlogPlan,
        project: Project,
        tenant_id: UUID,
        item: Dict[str, Any],
    ) -> BlogTopic:
        query = item["query"]
        return BlogTopic(
            tenant_id=tenant_id,
            project_id=project.id,
            blog_plan_id=plan.id,
            target_keyword=query[:255],
            search_intent=self._intent_for(query),
            title=self._title_for(query),
            angle=None,
            target_audience=getattr(project, "target_audience", None),
            priority_score=float(item["score"]),
            status=BlogTopicStatus.suggested,
            reason=self._reason_text(item),
        )

    def _reason_text(self, item: Dict[str, Any]) -> str:
        """Why this topic was chosen, in the words a reviewer needs."""
        lines = [f"Opportunity Score {item['score']}/100."]
        lines.extend(f"- {reason}" for reason in item.get("reasons", []))
        lines.append(
            "Score is computed from measured Search Console signals and site coverage. "
            "Search volume is not available without a paid provider and has not been estimated."
        )
        return "\n".join(lines)

    def _intent_for(self, query: str) -> BlogSearchIntent:
        lowered = (query or "").lower()
        if any(word in lowered for word in (" vs ", "versus", "compare", "alternative")):
            return BlogSearchIntent.comparison
        if any(word in lowered for word in ("near me", "in ", "local")):
            return BlogSearchIntent.local
        if any(word in lowered for word in ("buy", "price", "cost", "book", "hire", "quote")):
            return BlogSearchIntent.transactional
        if any(word in lowered for word in ("best", "top", "review", "service")):
            return BlogSearchIntent.commercial
        return BlogSearchIntent.informational

    def _title_for(self, query: str) -> str:
        cleaned = (query or "").strip()
        if not cleaned:
            return "Untitled topic"
        return (cleaned[0].upper() + cleaned[1:])[:255]

    async def _gsc_by_page(
        self,
        project_id: UUID,
        tenant_id: UUID,
        *,
        days: int,
        offset_days: int = 0,
    ) -> Dict[str, Dict[str, Any]]:
        """Search Console totals per URL slug, for one window."""
        end = datetime.utcnow() - timedelta(days=offset_days)
        start = end - timedelta(days=days - offset_days if offset_days else days)
        result = await self.db.execute(
            select(
                SearchConsoleRow.page_url,
                SearchConsoleRow.clicks,
                SearchConsoleRow.impressions,
                SearchConsoleRow.position,
            ).where(
                SearchConsoleRow.project_id == project_id,
                SearchConsoleRow.tenant_id == tenant_id,
                SearchConsoleRow.date_start >= start,
                SearchConsoleRow.date_start <= end,
            )
        )
        pages: Dict[str, Dict[str, Any]] = {}
        for page_url, clicks, impressions, position in result.all():
            slug = (page_url or "").rstrip("/").rsplit("/", 1)[-1].lower()
            if not slug:
                continue
            row = pages.setdefault(slug, {"clicks": 0, "impressions": 0, "position": None, "_n": 0})
            row["clicks"] += int(clicks or 0)
            row["impressions"] += int(impressions or 0)
            if position:
                previous = row["position"] or 0.0
                row["_n"] += 1
                row["position"] = ((previous * (row["_n"] - 1)) + float(position)) / row["_n"]
        return pages
