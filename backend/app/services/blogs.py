"""Blog planner and draft generation using local SEO signals and local Ollama."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.blog import (
    BlogDraft,
    BlogDraftStatus,
    BlogPlan,
    BlogPlanStatus,
    BlogSearchIntent,
    BlogTopic,
    BlogTopicStatus,
)
from app.repositories.blogs import BlogRepository
from app.services.knowledge import KnowledgeService
from app.services.local_llm import LocalLLMError, LocalLLMService, OllamaRequestError

logger = structlog.get_logger(__name__)

TITLE_MAX_LENGTH = 60
META_MAX_LENGTH = 160


class BlogService:
    """Plan buyer-intent topics and generate markdown drafts from local RAG."""

    def __init__(
        self,
        db: AsyncSession,
        llm_service: Optional[LocalLLMService] = None,
        knowledge_service: Optional[KnowledgeService] = None,
    ):
        self.db = db
        self.repository = BlogRepository(db)
        self.llm_service = llm_service or LocalLLMService()
        self.knowledge_service = knowledge_service or KnowledgeService(db)

    async def create_plan(
        self,
        tenant_id: UUID,
        title: str,
        description: Optional[str] = None,
        target_site_url: Optional[str] = None,
        project_id: Optional[UUID] = None,
        blogs_per_week: int = 3,
    ) -> BlogPlan:
        clean_title = self._clean_text(title)[:255]
        if not clean_title:
            raise ValueError("Blog plan title is required")
        plan = await self.repository.create_plan(
            tenant_id=tenant_id,
            project_id=project_id,
            title=clean_title,
            description=self._clean_text(description or "") or None,
            target_site_url=self._clean_text(target_site_url or "") or None,
            blogs_per_week=max(1, min(20, int(blogs_per_week or 3))),
        )
        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def list_plans(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        status: Optional[BlogPlanStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogPlan]:
        return await self.repository.list_plans(tenant_id, project_id, status, limit, offset)

    async def get_plan(self, plan_id: UUID, tenant_id: UUID) -> Optional[BlogPlan]:
        return await self.repository.get_plan(plan_id, tenant_id)

    async def generate_topics(
        self,
        plan_id: UUID,
        tenant_id: UUID,
        count: Optional[int] = None,
    ) -> List[BlogTopic]:
        plan = await self.repository.get_plan(plan_id, tenant_id)
        if not plan:
            raise ValueError("Blog plan not found")
        topic_count = max(1, min(20, int(count or plan.blogs_per_week or 3)))
        context = await self._planning_context(plan)
        payload = await self._generate_topics_payload(plan, context, topic_count)
        records = self._topic_records(plan, payload, context, topic_count)
        if len(records) < topic_count:
            fallback_context = dict(context)
            fallback_context["existing_keywords"] = set(context["existing_keywords"]).union(
                self._keyword_key(record["target_keyword"]) for record in records
            )
            records.extend(self._fallback_topic_records(plan, fallback_context, topic_count - len(records)))
        created = await self.repository.add_topics(records)
        if created:
            await self.repository.set_plan_status(plan, BlogPlanStatus.active)
        await self.db.commit()
        return await self.repository.list_topics(plan.id, tenant_id, limit=topic_count)

    async def list_topics(
        self,
        plan_id: UUID,
        tenant_id: UUID,
        status: Optional[BlogTopicStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogTopic]:
        plan = await self.repository.get_plan(plan_id, tenant_id)
        if not plan:
            raise ValueError("Blog plan not found")
        return await self.repository.list_topics(plan_id, tenant_id, status=status, limit=limit, offset=offset)

    async def update_topic_status(
        self,
        topic_id: UUID,
        tenant_id: UUID,
        status: BlogTopicStatus,
    ) -> BlogTopic:
        topic = await self.repository.get_topic(topic_id, tenant_id)
        if not topic:
            raise ValueError("Blog topic not found")
        topic = await self.repository.set_topic_status(topic, status)
        await self.db.commit()
        await self.db.refresh(topic)
        return topic

    async def draft_topic(self, topic_id: UUID, tenant_id: UUID) -> BlogDraft:
        topic = await self.repository.get_topic(topic_id, tenant_id)
        if not topic:
            raise ValueError("Blog topic not found")
        if topic.status not in {BlogTopicStatus.approved, BlogTopicStatus.drafted}:
            raise ValueError("Blog topic must be approved before drafting")
        plan = await self.repository.get_plan(topic.blog_plan_id, tenant_id)
        if not plan:
            raise ValueError("Blog plan not found")

        context = await self._draft_context(plan, topic)
        payload = await self._generate_draft_payload(plan, topic, context)
        draft_values = self._draft_values(topic, payload, context)
        draft = await self.repository.create_draft(draft_values)
        await self.repository.set_topic_status(topic, BlogTopicStatus.drafted)
        await self.db.commit()
        await self.db.refresh(draft)
        return draft

    async def get_draft(self, draft_id: UUID, tenant_id: UUID) -> Optional[BlogDraft]:
        return await self.repository.get_draft(draft_id, tenant_id)

    async def list_drafts_for_plan(
        self,
        plan_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogDraft]:
        plan = await self.repository.get_plan(plan_id, tenant_id)
        if not plan:
            raise ValueError("Blog plan not found")
        return await self.repository.list_drafts_for_plan(plan_id, tenant_id, limit=limit, offset=offset)

    async def _planning_context(self, plan: BlogPlan) -> Dict[str, Any]:
        pages = await self.repository.list_candidate_pages(plan)
        page_ids = [page.id for page in pages]
        issues = await self.repository.list_audit_issues_for_pages(plan.tenant_id, page_ids)
        geo_scores = await self.repository.list_geo_scores_for_pages(plan.tenant_id, page_ids)
        geo_recs = await self.repository.list_geo_recommendations_for_pages(plan.tenant_id, page_ids)
        content_suggestions = await self.repository.list_content_suggestions_for_pages(plan.tenant_id, page_ids)
        internal_links = await self.repository.list_internal_link_recommendations_for_pages(plan.tenant_id, page_ids)
        semantic_content = await self.repository.list_semantic_content_for_pages(plan.tenant_id, page_ids)
        existing_keywords = await self.repository.existing_topic_keywords(plan.id, plan.tenant_id)
        topic_query = self._clean_text(" ".join([plan.title, plan.description or "", plan.target_site_url or ""]))
        knowledge = await self._knowledge_results(
            tenant_id=plan.tenant_id,
            project_id=plan.project_id,
            topic=topic_query or plan.title,
            limit=6,
        )

        issues_by_page = defaultdict(list)
        for issue in issues:
            if issue.crawl_page_id:
                issues_by_page[issue.crawl_page_id].append(issue)
        latest_geo = {}
        for score in geo_scores:
            latest_geo.setdefault(score.page_id, score)
        semantic_counts = Counter(content.crawl_page_id for content in semantic_content)
        internal_by_page = defaultdict(list)
        for rec in internal_links:
            internal_by_page[rec.source_page_id].append(rec)
            internal_by_page[rec.target_page_id].append(rec)
        content_by_page = defaultdict(list)
        for suggestion in content_suggestions:
            content_by_page[suggestion.page_id].append(suggestion)
        geo_recs_by_page = defaultdict(list)
        for rec in geo_recs:
            geo_recs_by_page[rec.page_id].append(rec)

        return {
            "pages": pages,
            "issues_by_page": issues_by_page,
            "geo_scores_by_page": latest_geo,
            "geo_recs_by_page": geo_recs_by_page,
            "content_suggestions_by_page": content_by_page,
            "internal_recs_by_page": internal_by_page,
            "semantic_counts": semantic_counts,
            "existing_keywords": existing_keywords,
            "knowledge": knowledge,
        }

    async def _draft_context(self, plan: BlogPlan, topic: BlogTopic) -> Dict[str, Any]:
        pages = await self.repository.list_candidate_pages(plan, limit=25)
        landing_page = next((page for page in pages if page.id == topic.target_landing_page_id), None)
        page_id = landing_page.id if landing_page else topic.target_landing_page_id
        knowledge = await self._knowledge_results(
            tenant_id=plan.tenant_id,
            project_id=plan.project_id,
            topic=f"{topic.target_keyword} {topic.title} {topic.angle or ''}",
            page_id=page_id,
            limit=8,
        )
        page_ids = [page.id for page in pages]
        internal_recs = await self.repository.list_internal_link_recommendations_for_pages(plan.tenant_id, page_ids)
        content_suggestions = await self.repository.list_content_suggestions_for_pages(plan.tenant_id, page_ids)
        return {
            "pages": pages,
            "landing_page": landing_page,
            "knowledge": knowledge,
            "internal_recs": internal_recs,
            "content_suggestions": content_suggestions,
        }

    async def _knowledge_results(
        self,
        tenant_id: UUID,
        topic: str,
        project_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        try:
            payload = await self.knowledge_service.relevant_knowledge(
                tenant_id=tenant_id,
                project_id=project_id,
                topic=topic,
                page_id=page_id,
                limit=limit,
            )
            return payload.get("results", [])
        except Exception as exc:
            logger.warning("Knowledge retrieval unavailable for blog workflow", error=str(exc))
            return []

    async def _generate_topics_payload(self, plan: BlogPlan, context: Dict[str, Any], count: int) -> Dict[str, Any]:
        prompt = self._topic_prompt(plan, context, count)
        try:
            response = await self.llm_service.generate(
                prompt,
                model=settings.OLLAMA_DEFAULT_MODEL,
                options={"temperature": 0.25, "num_predict": 1400},
            )
            return self._parse_json(response.get("response", ""))
        except (OllamaRequestError, json.JSONDecodeError):
            return {}
        except LocalLLMError:
            raise

    async def _generate_draft_payload(self, plan: BlogPlan, topic: BlogTopic, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._draft_prompt(plan, topic, context)
        try:
            response = await self.llm_service.generate(
                prompt,
                model=settings.OLLAMA_DEFAULT_MODEL,
                options={"temperature": 0.2, "num_predict": 2800},
            )
            return self._parse_json(response.get("response", ""))
        except (OllamaRequestError, json.JSONDecodeError):
            return {}
        except LocalLLMError:
            raise

    def _topic_prompt(self, plan: BlogPlan, context: Dict[str, Any], count: int) -> str:
        page_payload = []
        for page in context["pages"][:10]:
            geo = context["geo_scores_by_page"].get(page.id)
            issue_types = [issue.issue_type for issue in context["issues_by_page"][page.id]][:8]
            page_payload.append(
                {
                    "page_id": str(page.id),
                    "url": page.url,
                    "title": page.title,
                    "h1": page.h1 or [],
                    "word_count": page.word_count,
                    "internal_links": page.internal_links,
                    "geo_score": getattr(geo, "geo_score", None),
                    "aeo_score": getattr(geo, "aeo_score", None),
                    "issues": issue_types,
                    "semantic_units": int(context["semantic_counts"][page.id]),
                }
            )
        knowledge_payload = [
            {
                "title": item.get("title"),
                "source_type": item.get("source_type"),
                "text_preview": item.get("text_preview") or item.get("chunk_text", "")[:300],
            }
            for item in context["knowledge"][:6]
        ]
        return (
            "You are a local SEO blog strategist inside a self-hosted app. "
            "Use only the supplied crawl and knowledge data. Return only valid JSON. "
            "Do not invent search volume, statistics, or unsupported claims. "
            "Generate buyer-intent blog topics that support existing landing pages and avoid duplicates.\n\n"
            "JSON shape:\n"
            "{\n"
            '  "topics": [\n'
            '    {"target_keyword": "...", "search_intent": "informational|commercial|transactional|local|comparison", '
            '"title": "...", "angle": "...", "target_audience": "...", "target_landing_page_id": "uuid-or-null", '
            '"priority_score": 0-100, "reason": "..."}\n'
            "  ]\n"
            "}\n\n"
            f"Requested topics: {count}\n"
            f"Plan title: {plan.title}\n"
            f"Plan description: {plan.description or ''}\n"
            f"Target site: {plan.target_site_url or ''}\n"
            f"Existing topic keywords to avoid: {json.dumps(sorted(context['existing_keywords']))}\n"
            f"Candidate landing pages: {json.dumps(page_payload)}\n"
            f"Knowledge chunks: {json.dumps(knowledge_payload)}\n"
        )

    def _draft_prompt(self, plan: BlogPlan, topic: BlogTopic, context: Dict[str, Any]) -> str:
        landing_page = context.get("landing_page")
        pages = [
            {
                "page_id": str(page.id),
                "url": page.url,
                "title": page.title,
                "h1": page.h1 or [],
            }
            for page in context["pages"][:12]
        ]
        knowledge = [
            {
                "source_id": item.get("source_id"),
                "document_id": item.get("document_id"),
                "title": item.get("title"),
                "source_type": item.get("source_type"),
                "chunk_text": item.get("chunk_text") or item.get("text_preview"),
            }
            for item in context["knowledge"][:8]
        ]
        link_plan = self._internal_link_plan(topic, context)
        return (
            "You are a local SEO blog draft assistant inside a self-hosted app. "
            "Use only the supplied knowledge chunks and crawl data. Return only valid JSON. "
            "Do not invent fake statistics, customer names, certifications, prices, or guarantees. "
            "If information is missing, include a short 'Missing information to confirm' section instead of hallucinating. "
            "Output useful markdown, not generic filler.\n\n"
            "JSON shape:\n"
            "{\n"
            '  "title": "...",\n'
            '  "meta_title": "max 60 chars",\n'
            '  "meta_description": "max 160 chars",\n'
            '  "outline": {"h1": "...", "intro_angle": "...", "sections": [{"h2": "...", "h3": ["..."]}], '
            '"faq": [{"question": "...", "answer": "..."}], "recommended_schema_type": "BlogPosting"},\n'
            '  "draft_markdown": "# ...",\n'
            '  "faq_json": [{"question": "...", "answer": "..."}],\n'
            '  "schema_json": {"@context": "https://schema.org", "@type": "BlogPosting"},\n'
            '  "internal_link_plan": [{"url": "...", "anchor": "...", "reason": "..."}]\n'
            "}\n\n"
            f"Plan: {plan.title} - {plan.description or ''}\n"
            f"Topic keyword: {topic.target_keyword}\n"
            f"Topic title: {topic.title}\n"
            f"Intent: {topic.search_intent.value if hasattr(topic.search_intent, 'value') else topic.search_intent}\n"
            f"Angle: {topic.angle or ''}\n"
            f"Audience: {topic.target_audience or ''}\n"
            f"Target landing page: {landing_page.url if landing_page else ''}\n"
            f"Existing pages for internal links: {json.dumps(pages)}\n"
            f"Recommended internal links: {json.dumps(link_plan)}\n"
            f"Knowledge chunks to ground the draft: {json.dumps(knowledge)}\n"
        )

    def _topic_records(self, plan: BlogPlan, payload: Dict[str, Any], context: Dict[str, Any], count: int) -> List[dict]:
        topics = payload.get("topics") or payload.get("blog_topics") or []
        if not isinstance(topics, list):
            return []
        records = []
        existing = set(context["existing_keywords"])
        page_ids = {str(page.id): page.id for page in context["pages"]}
        for item in topics:
            if not isinstance(item, dict):
                continue
            keyword = self._clean_text(str(item.get("target_keyword") or item.get("keyword") or ""))
            key = self._keyword_key(keyword)
            if not keyword or key in existing or self._is_near_duplicate(key, existing):
                continue
            title = self._clean_text(str(item.get("title") or keyword.title()))[:255]
            intent = self._intent(item.get("search_intent"))
            page_id_raw = str(item.get("target_landing_page_id") or "")
            target_page = next((page for page in context["pages"] if str(page.id) == page_id_raw), None)
            target_page_id = target_page.id if target_page and self._page_matches_topic(target_page, keyword, title) else None
            priority = self._float_score(item.get("priority_score"), default=70)
            records.append(
                {
                    "tenant_id": plan.tenant_id,
                    "project_id": plan.project_id,
                    "blog_plan_id": plan.id,
                    "target_keyword": keyword[:255],
                    "search_intent": intent,
                    "title": title or keyword.title(),
                    "angle": self._clean_text(str(item.get("angle") or "")) or None,
                    "target_audience": self._clean_text(str(item.get("target_audience") or ""))[:255] or None,
                    "target_landing_page_id": target_page_id,
                    "priority_score": priority,
                    "status": BlogTopicStatus.suggested,
                    "reason": self._clean_text(str(item.get("reason") or "Generated from local crawl and knowledge signals.")),
                }
            )
            existing.add(key)
            if len(records) >= count:
                break
        return records

    def _fallback_topic_records(self, plan: BlogPlan, context: Dict[str, Any], count: int) -> List[dict]:
        records = []
        existing = set(context["existing_keywords"])
        pages = context["pages"] or [None]
        for page in pages:
            topic = self._page_topic(page) if page else plan.title
            keyword = self._clean_text(f"{topic} guide for buyers")
            key = self._keyword_key(keyword)
            if key in existing:
                continue
            records.append(
                {
                    "tenant_id": plan.tenant_id,
                    "project_id": plan.project_id,
                    "blog_plan_id": plan.id,
                    "target_keyword": keyword[:255],
                    "search_intent": BlogSearchIntent.commercial,
                    "title": f"How to Choose {topic} With Confidence"[:255],
                    "angle": "Buyer-intent guide grounded in existing site and knowledge base signals.",
                    "target_audience": "Service buyers",
                    "target_landing_page_id": getattr(page, "id", None),
                    "priority_score": 65.0,
                    "status": BlogTopicStatus.suggested,
                    "reason": "Fallback topic generated from local crawl data because Ollama returned incomplete JSON.",
                }
            )
            existing.add(key)
            if len(records) >= count:
                break
        return records

    def _draft_values(self, topic: BlogTopic, payload: Dict[str, Any], context: Dict[str, Any]) -> dict:
        if not self._payload_is_grounded(payload, context):
            payload = {}
        title = self._clean_text(str(payload.get("title") or topic.title))[:255]
        outline = self._validate_outline(payload.get("outline"), topic, context)
        faq = self._validate_faq(payload.get("faq_json") or outline.get("faq"), topic)
        internal_link_plan = self._validate_internal_link_plan(
            payload.get("internal_link_plan"),
            topic,
            context,
        )
        markdown = self._clean_markdown(str(payload.get("draft_markdown") or ""))
        if not markdown:
            markdown = self._fallback_markdown(topic, outline, context)
        meta_title = self._truncate(self._clean_text(str(payload.get("meta_title") or title)), TITLE_MAX_LENGTH)
        meta_description = self._truncate(
            self._clean_text(str(payload.get("meta_description") or f"Learn {topic.target_keyword} with practical guidance grounded in the business knowledge base.")),
            META_MAX_LENGTH,
        )
        schema = self._validate_schema(payload.get("schema_json"), title, meta_description)
        knowledge_sources = self._knowledge_sources_used(context["knowledge"])
        return {
            "tenant_id": topic.tenant_id,
            "project_id": topic.project_id,
            "blog_topic_id": topic.id,
            "title": title,
            "slug": self._slugify(title),
            "meta_title": meta_title,
            "meta_description": meta_description,
            "outline": outline,
            "draft_markdown": markdown,
            "faq_json": faq,
            "schema_json": schema,
            "internal_link_plan": internal_link_plan,
            "knowledge_sources_used": knowledge_sources,
            "status": BlogDraftStatus.draft,
        }

    def _validate_outline(self, value: Any, topic: BlogTopic, context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, dict):
            value = {}
        sections = value.get("sections")
        if not isinstance(sections, list) or not sections:
            sections = [
                {"h2": f"What buyers should know about {topic.target_keyword}", "h3": ["Key decision factors"]},
                {"h2": "How the service approach works", "h3": ["Common questions", "Next steps"]},
            ]
        return {
            "h1": self._clean_text(str(value.get("h1") or topic.title)),
            "intro_angle": self._clean_text(str(value.get("intro_angle") or topic.angle or "")),
            "sections": sections[:8],
            "faq": self._validate_faq(value.get("faq"), topic),
            "recommended_schema_type": self._clean_text(str(value.get("recommended_schema_type") or "BlogPosting")),
            "knowledge_sources_to_use": self._knowledge_sources_used(context["knowledge"]),
        }

    def _validate_faq(self, value: Any, topic: BlogTopic) -> List[Dict[str, str]]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = []
        if not isinstance(value, list):
            value = []
        faqs = []
        for item in value:
            if not isinstance(item, dict):
                continue
            question = self._clean_text(str(item.get("question") or ""))
            answer = self._clean_text(str(item.get("answer") or ""))
            if question and answer:
                faqs.append({"question": question, "answer": answer})
        if faqs:
            return faqs[:5]
        return [
            {
                "question": f"What should buyers know about {topic.target_keyword}?",
                "answer": "Buyers should confirm the details against the business knowledge base and choose next steps based on their service goals.",
            }
        ]

    def _validate_schema(self, value: Any, title: str, meta_description: str) -> Dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {}
        if not isinstance(value, dict):
            value = {}
        value["@context"] = "https://schema.org"
        if value.get("@type") not in {"BlogPosting", "Article"}:
            value["@type"] = "BlogPosting"
        value.setdefault("headline", title)
        value.setdefault("description", meta_description)
        return value

    def _validate_internal_link_plan(self, value: Any, topic: BlogTopic, context: Dict[str, Any]) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            value = []
        links = []
        for item in value:
            if not isinstance(item, dict):
                continue
            url = self._clean_text(str(item.get("url") or ""))
            anchor = self._clean_text(str(item.get("anchor") or ""))
            reason = self._clean_text(str(item.get("reason") or ""))
            page = self._page_for_url(url, context.get("pages", []))
            if url and anchor and page and self._page_matches_topic(page, topic.target_keyword, topic.title):
                links.append({"url": url, "anchor": anchor, "reason": reason or "Relevant internal link."})
        if links:
            return links[:8]
        return self._internal_link_plan(topic, context)

    def _internal_link_plan(self, topic: BlogTopic, context: Dict[str, Any]) -> List[Dict[str, str]]:
        links = []
        landing = context.get("landing_page")
        if landing and self._page_matches_topic(landing, topic.target_keyword, topic.title):
            links.append(
                {
                    "url": landing.url,
                    "anchor": self._clean_text(landing.title or topic.target_keyword)[:80],
                    "reason": "Primary landing page this blog should support.",
                }
            )
        for rec in context.get("internal_recs", [])[:4]:
            target_url = getattr(rec, "target_url", None)
            anchor = getattr(rec, "suggested_anchor_text", None)
            page = self._page_for_url(target_url or "", context.get("pages", []))
            if (
                target_url
                and anchor
                and page
                and self._page_matches_topic(page, topic.target_keyword, topic.title)
                and all(link["url"] != target_url for link in links)
            ):
                links.append({"url": target_url, "anchor": anchor, "reason": getattr(rec, "reason", "Internal link recommendation.")})
        for page in context.get("pages", [])[:6]:
            if not self._page_matches_topic(page, topic.target_keyword, topic.title):
                continue
            if all(link["url"] != page.url for link in links):
                links.append(
                    {
                        "url": page.url,
                        "anchor": self._clean_text(page.title or topic.target_keyword)[:80],
                        "reason": "Related crawled page for contextual support.",
                    }
                )
            if len(links) >= 5:
                break
        return links[:8]

    def _knowledge_sources_used(self, knowledge: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        sources = []
        for item in knowledge:
            source_id = item.get("source_id")
            document_id = item.get("document_id")
            key = (source_id, document_id)
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "source_id": source_id,
                    "document_id": document_id,
                    "title": item.get("title"),
                    "source_type": item.get("source_type"),
                    "score": item.get("score"),
                }
            )
        return sources[:8]

    def _payload_is_grounded(self, payload: Dict[str, Any], context: Dict[str, Any]) -> bool:
        if not payload:
            return False
        knowledge_text = " ".join(
            self._clean_text(item.get("chunk_text") or item.get("text_preview") or "")
            for item in context.get("knowledge", [])
        ).lower()
        generated_text = json.dumps(payload, ensure_ascii=False).lower()
        if re.search(r"\b\d+\s*[-–]\s*\d+\s*(day|week|month|year)s?\b", generated_text):
            return False
        risky_phrases = [
            "electrician client success",
            "plumber client improvement",
            "success story",
            "success stories",
            "real-world examples",
            "guarantee",
            "certified",
        ]
        for phrase in risky_phrases:
            if phrase in generated_text and phrase not in knowledge_text:
                return False
        return True

    def _fallback_markdown(self, topic: BlogTopic, outline: Dict[str, Any], context: Dict[str, Any]) -> str:
        knowledge_text = "\n\n".join(
            self._clean_text(item.get("chunk_text") or item.get("text_preview") or "")
            for item in context["knowledge"][:4]
        )
        missing = ""
        if not knowledge_text:
            missing = "\n\n## Missing information to confirm\n\n- Add source knowledge about services, examples, proof points, and FAQs before publishing.\n"
        return (
            f"# {outline['h1']}\n\n"
            f"{topic.angle or 'This draft is grounded in the available knowledge base and crawl signals.'}\n\n"
            f"## What buyers should know\n\n{knowledge_text or 'Use the business knowledge base to complete this section.'}\n\n"
            "## Practical next steps\n\nReview the linked landing page, confirm service details, and add any missing proof before publishing."
            f"{missing}"
        )

    def _parse_json(self, text: str) -> Dict[str, Any]:
        stripped = (text or "").strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
            stripped = re.sub(r"```$", "", stripped).strip()
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\})", stripped, re.DOTALL)
            if not match:
                raise OllamaRequestError("Ollama response did not contain valid JSON.")
            data = json.loads(match.group(1))
        if not isinstance(data, dict):
            raise OllamaRequestError("Ollama JSON response must be an object.")
        return data

    def _intent(self, value: Any) -> BlogSearchIntent:
        raw = str(value or "").lower()
        for intent in BlogSearchIntent:
            if raw == intent.value:
                return intent
        if "near" in raw or "local" in raw or "city" in raw:
            return BlogSearchIntent.local
        if "vs" in raw or "compare" in raw:
            return BlogSearchIntent.comparison
        if "cost" in raw or "best" in raw or "service" in raw:
            return BlogSearchIntent.commercial
        return BlogSearchIntent.informational

    def _float_score(self, value: Any, default: float) -> float:
        try:
            return round(max(0.0, min(100.0, float(value))), 2)
        except (TypeError, ValueError):
            return default

    def _keyword_key(self, value: str) -> str:
        return " ".join((value or "").lower().split())

    def _is_near_duplicate(self, key: str, existing: set[str]) -> bool:
        words = set(re.findall(r"[a-z0-9]{3,}", key))
        if not words:
            return False
        for item in existing:
            other = set(re.findall(r"[a-z0-9]{3,}", item))
            if other and len(words.intersection(other)) / max(len(words.union(other)), 1) >= 0.82:
                return True
        return False

    def _page_topic(self, page: Any) -> str:
        if not page:
            return "Service"
        for values in [page.h1 or [], [page.title or ""]]:
            if isinstance(values, str):
                values = [values]
            for value in values:
                cleaned = self._clean_text(str(value))
                if cleaned and cleaned.lower() not in {"home", "homepage", "login", "quotes to scrape"}:
                    return cleaned
        parts = [part for part in page.url.rstrip("/").split("/") if part and not part.isdigit()]
        return self._clean_text(parts[-1].replace("-", " ").title()) if parts else "Service"

    def _page_matches_topic(self, page: Any, keyword: str, title: str) -> bool:
        page_text = " ".join(
            [
                page.url or "",
                page.title or "",
                " ".join(str(value) for value in (page.h1 or [])) if not isinstance(page.h1, str) else page.h1,
            ]
        )
        topic_tokens = self._semantic_tokens(f"{keyword} {title}")
        page_tokens = self._semantic_tokens(page_text)
        if not topic_tokens or not page_tokens:
            return False
        return bool(topic_tokens.intersection(page_tokens))

    def _page_for_url(self, url: str, pages: List[Any]) -> Optional[Any]:
        clean = (url or "").split("#", 1)[0].rstrip("/").lower()
        for page in pages:
            if (page.url or "").split("#", 1)[0].rstrip("/").lower() == clean:
                return page
        return None

    def _semantic_tokens(self, value: str) -> set[str]:
        stopwords = {
            "about",
            "blog",
            "business",
            "company",
            "guide",
            "home",
            "landing",
            "local",
            "page",
            "pages",
            "service",
            "services",
            "studio",
            "what",
            "with",
            "your",
        }
        tokens = set()
        for token in re.findall(r"[a-z0-9]{4,}", value.lower()):
            if token in stopwords:
                continue
            tokens.add(token)
            if token.endswith("s") and len(token) > 5:
                tokens.add(token[:-1])
            if token.endswith("ing") and len(token) > 7:
                tokens.add(token[:-3])
            if len(token) > 6:
                tokens.add(token[:5])
        return tokens

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug[:120] or "blog-draft"

    def _truncate(self, value: str, max_length: int) -> str:
        value = self._clean_text(value)
        if len(value) <= max_length:
            return value
        return value[:max_length].rsplit(" ", 1)[0].strip() or value[:max_length].strip()

    def _clean_markdown(self, value: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", (value or "").strip())

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())
