"""Local-LLM-powered content optimization suggestions."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.content_optimization import (
    ContentOptimizationRun,
    ContentOptimizationRunStatus,
    ContentOptimizationSuggestion,
    ContentOptimizationSuggestionStatus,
    ContentOptimizationSuggestionType,
)
from app.repositories.content_optimization import ContentOptimizationRepository, SuggestionKey
from app.services.local_llm import LocalLLMError, LocalLLMService, OllamaRequestError
from app.services.project_context import project_context_prompt

logger = structlog.get_logger(__name__)


TITLE_MIN_LENGTH = 30
TITLE_MAX_LENGTH = 60
META_MIN_LENGTH = 50
META_MAX_LENGTH = 160
GENERIC_TITLES = {"home", "homepage", "untitled", "quotes to scrape", "login"}


class ContentOptimizationService:
    """Generate safe page-level content optimization suggestions with local Ollama."""

    def __init__(
        self,
        db: AsyncSession,
        llm_service: Optional[LocalLLMService] = None,
    ):
        self.db = db
        self.repository = ContentOptimizationRepository(db)
        self.llm_service = llm_service or LocalLLMService()

    async def start_generation(self, crawl_id: UUID, tenant_id: UUID) -> ContentOptimizationRun:
        crawl = await self.repository.get_crawl(crawl_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")
        pages = await self.repository.list_crawl_pages(crawl_id)
        if not pages:
            raise ValueError("Crawl has no pages")

        run = await self.repository.create_run(crawl, model=settings.OLLAMA_DEFAULT_MODEL)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Created content optimization run", run_id=str(run.id), crawl_id=str(crawl_id))
        return run

    async def execute_generation(self, run_id: UUID) -> ContentOptimizationRun:
        run = await self.repository.get_run(run_id)
        if not run:
            raise ValueError("Content optimization run not found")

        await self.repository.set_run_status(run, ContentOptimizationRunStatus.running, progress=5)
        await self.db.commit()

        try:
            crawl = await self.repository.get_crawl(run.crawl_id, run.tenant_id)
            if not crawl:
                raise ValueError("Crawl not found")
            project = None
            if getattr(crawl, "project_id", None):
                project = await self.repository.get_project(crawl.project_id, crawl.tenant_id)
            project_context_text = project_context_prompt(project)

            pages = await self.repository.list_crawl_pages(run.crawl_id)
            audit_issues = await self.repository.list_audit_issues(run.crawl_id, run.tenant_id)
            page_scores = await self.repository.list_page_scores(run.crawl_id, run.tenant_id)
            internal_links = await self.repository.list_internal_link_recommendations(run.crawl_id, run.tenant_id)
            existing_keys = await self.repository.existing_suggestion_keys(run.crawl_id, run.tenant_id)

            issues_by_page = defaultdict(list)
            for issue in audit_issues:
                if issue.crawl_page_id:
                    issues_by_page[issue.crawl_page_id].append(issue)
            scores_by_page = {score.crawl_page_id: score for score in page_scores}
            link_recs_by_page = defaultdict(list)
            for rec in internal_links:
                link_recs_by_page[rec.source_page_id].append(rec)
                link_recs_by_page[rec.target_page_id].append(rec)

            created_count = 0
            for index, page in enumerate(pages, start=1):
                page_payload = await self._generate_page_payload(
                    page,
                    issues_by_page[page.id],
                    scores_by_page.get(page.id),
                    link_recs_by_page[page.id],
                    project_context_text,
                )
                records = self._suggestion_records(
                    run=run,
                    page=page,
                    payload=page_payload,
                    audit_issues=issues_by_page[page.id],
                    page_score=scores_by_page.get(page.id),
                    internal_link_recs=link_recs_by_page[page.id],
                    existing_keys=existing_keys,
                )
                if records:
                    created_count += await self.repository.add_suggestions(records)
                    for record in records:
                        existing_keys.add((record["page_id"], record["suggestion_type"], record["content_hash"]))

                run.progress = min(95, 5 + int((index / max(len(pages), 1)) * 90))
                await self.db.commit()

            await self.repository.finish_run(run, total_pages=len(pages), total_suggestions=created_count)
            await self.repository.set_run_status(run, ContentOptimizationRunStatus.completed, progress=100)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info("Completed content optimization run", run_id=str(run.id), suggestions=created_count)
            return run
        except Exception as exc:
            await self.repository.set_run_status(
                run,
                ContentOptimizationRunStatus.failed,
                error_message=str(exc),
                progress=100,
            )
            await self.db.commit()
            logger.error("Content optimization failed", run_id=str(run.id), error=str(exc), exc_info=True)
            raise

    async def get_run_status(self, run_id: UUID, tenant_id: UUID) -> Optional[ContentOptimizationRun]:
        return await self.repository.get_run(run_id, tenant_id)

    async def list_suggestions(
        self,
        tenant_id: UUID,
        crawl_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        status: Optional[ContentOptimizationSuggestionStatus] = None,
        suggestion_type: Optional[ContentOptimizationSuggestionType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ContentOptimizationSuggestion]:
        return await self.repository.list_suggestions(
            tenant_id=tenant_id,
            crawl_id=crawl_id,
            page_id=page_id,
            status=status,
            suggestion_type=suggestion_type,
            limit=limit,
            offset=offset,
        )

    async def update_status(
        self,
        suggestion_id: UUID,
        tenant_id: UUID,
        status: ContentOptimizationSuggestionStatus,
    ) -> ContentOptimizationSuggestion:
        suggestion = await self.repository.get_suggestion(suggestion_id, tenant_id)
        if not suggestion:
            raise ValueError("Suggestion not found")
        suggestion = await self.repository.set_suggestion_status(suggestion, status)
        await self.db.commit()
        await self.db.refresh(suggestion)
        return suggestion

    async def summary(self, crawl_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        crawl = await self.repository.get_crawl(crawl_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")
        suggestions = await self.repository.list_suggestions(tenant_id=tenant_id, crawl_id=crawl_id, limit=1000)
        page_ids = {suggestion.page_id for suggestion in suggestions}
        return {
            "crawl_id": crawl_id,
            "project_id": crawl.project_id,
            "total_suggestions": len(suggestions),
            "pages_with_suggestions": len(page_ids),
            "average_priority_score": self._average([float(item.priority_score or 0) for item in suggestions]),
            "average_confidence_score": self._average([float(item.confidence_score or 0) for item in suggestions]),
            "suggestions_by_status": await self.repository.count_by_status(crawl_id, tenant_id),
            "suggestions_by_type": await self.repository.count_by_type(crawl_id, tenant_id),
        }

    async def _generate_page_payload(
        self,
        page,
        audit_issues: List[Any],
        page_score: Optional[Any],
        internal_link_recs: List[Any],
        project_context_text: str,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(page, audit_issues, page_score, internal_link_recs, project_context_text)
        try:
            response = await self.llm_service.generate(
                prompt,
                model=settings.OLLAMA_DEFAULT_MODEL,
                options={"temperature": 0.2, "num_predict": 1200},
            )
            return self._parse_llm_json(response.get("response", ""))
        except OllamaRequestError:
            raise
        except LocalLLMError:
            raise

    def _suggestion_records(
        self,
        run: ContentOptimizationRun,
        page,
        payload: Dict[str, Any],
        audit_issues: List[Any],
        page_score: Optional[Any],
        internal_link_recs: List[Any],
        existing_keys: set[SuggestionKey],
    ) -> List[Dict[str, Any]]:
        issue_types = {issue.issue_type for issue in audit_issues}
        target_types = self._target_types(page, issue_types, internal_link_recs)
        records: List[Dict[str, Any]] = []
        for suggestion_type in target_types:
            current_value = self._current_value(page, suggestion_type, internal_link_recs)
            content_hash = self._content_hash(page, suggestion_type, current_value, issue_types)
            key = (page.id, suggestion_type, content_hash)
            if key in existing_keys:
                continue

            llm_item = self._payload_item(payload, suggestion_type)
            suggested_value = self._validated_suggested_value(page, suggestion_type, llm_item, internal_link_recs)
            if not suggested_value:
                continue

            records.append(
                {
                    "run_id": run.id,
                    "tenant_id": run.tenant_id,
                    "project_id": run.project_id,
                    "crawl_id": run.crawl_id,
                    "page_id": page.id,
                    "suggestion_type": suggestion_type,
                    "current_value": current_value,
                    "suggested_value": suggested_value,
                    "reason": self._reason(suggestion_type, llm_item, issue_types, page_score),
                    "priority_score": self._priority_score(suggestion_type, issue_types, page_score, internal_link_recs),
                    "confidence_score": self._confidence_score(suggestion_type, llm_item, suggested_value),
                    "status": ContentOptimizationSuggestionStatus.suggested,
                    "content_hash": content_hash,
                    "evidence": {
                        "url": page.url,
                        "audit_issue_types": sorted(issue_types),
                        "page_score": getattr(page_score, "score", None),
                        "word_count": int(page.word_count or 0),
                        "internal_link_recommendations": len(internal_link_recs),
                        "model": run.model,
                    },
                }
            )
        return records

    def _target_types(
        self,
        page,
        issue_types: set[str],
        internal_link_recs: List[Any],
    ) -> List[ContentOptimizationSuggestionType]:
        values = [
            ContentOptimizationSuggestionType.seo_title,
            ContentOptimizationSuggestionType.meta_description,
            ContentOptimizationSuggestionType.headings,
            ContentOptimizationSuggestionType.faq,
            ContentOptimizationSuggestionType.schema,
            ContentOptimizationSuggestionType.content_refresh,
            ContentOptimizationSuggestionType.answer_block,
        ]
        h1_source = page.h1 or []
        if isinstance(h1_source, str):
            h1_source = [h1_source]
        h1_values = [value for value in h1_source if str(value).strip()]
        if "missing_h1" in issue_types or "multiple_h1" in issue_types or len(h1_values) != 1:
            values.insert(2, ContentOptimizationSuggestionType.h1)
        if internal_link_recs:
            values.append(ContentOptimizationSuggestionType.internal_link_context)
        return values

    def _build_prompt(
        self,
        page,
        audit_issues: List[Any],
        page_score: Optional[Any],
        internal_link_recs: List[Any],
        project_context_text: str = "",
    ) -> str:
        issue_types = [issue.issue_type for issue in audit_issues]
        text_preview = re.sub(r"\s+", " ", (page.text_content or "").strip())[:1500]
        h1 = page.h1 or []
        h2 = page.h2 or []
        h3 = page.h3 or []
        link_context = [
            {
                "source_url": rec.source_url,
                "target_url": rec.target_url,
                "anchor": rec.suggested_anchor_text,
                "reason": rec.reason,
            }
            for rec in internal_link_recs[:5]
        ]
        return (
            "You are a local SEO assistant running inside a self-hosted app. "
            "Return only valid JSON. Do not rewrite the whole page. Do not create spammy or keyword-stuffed text. "
            "Make concise page-level suggestions only; no visual/UI/UX changes and no publishing instructions.\n\n"
            f"{project_context_text}\n\n"
            "JSON shape:\n"
            "{\n"
            '  "seo_title": {"suggested_value": "30-60 char title", "reason": "...", "confidence_score": 0-100},\n'
            '  "meta_description": {"suggested_value": "50-160 char meta description", "reason": "...", "confidence_score": 0-100},\n'
            '  "h1": {"suggested_value": "one H1 if needed", "reason": "...", "confidence_score": 0-100},\n'
            '  "headings": {"suggested_value": ["H2 or H3 suggestion"], "reason": "...", "confidence_score": 0-100},\n'
            '  "faq": {"suggested_value": [{"question": "...", "answer": "..."}], "reason": "...", "confidence_score": 0-100},\n'
            '  "schema": {"suggested_value": {"@context": "https://schema.org", "@type": "WebPage"}, "reason": "...", "confidence_score": 0-100},\n'
            '  "content_refresh": {"suggested_value": ["short recommendation"], "reason": "...", "confidence_score": 0-100},\n'
            '  "answer_block": {"suggested_value": "40-60 word direct answer", "reason": "...", "confidence_score": 0-100},\n'
            '  "internal_link_context": {"suggested_value": ["sentence showing where to place a suggested internal link"], "reason": "...", "confidence_score": 0-100}\n'
            "}\n\n"
            f"URL: {page.url}\n"
            f"Current title: {page.title or ''}\n"
            f"Current meta description: {page.meta_description or ''}\n"
            f"H1: {json.dumps(h1)}\n"
            f"H2: {json.dumps(h2)}\n"
            f"H3: {json.dumps(h3)}\n"
            f"Word count: {int(page.word_count or 0)}\n"
            f"SEO score: {getattr(page_score, 'score', None)}\n"
            f"Audit issues: {json.dumps(issue_types)}\n"
            f"Internal link recommendations: {json.dumps(link_context)}\n"
            f"Page text preview: {text_preview}\n"
        )

    def _parse_llm_json(self, text: str) -> Dict[str, Any]:
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

    def _payload_item(self, payload: Dict[str, Any], suggestion_type: ContentOptimizationSuggestionType) -> Dict[str, Any]:
        item = payload.get(suggestion_type.value) or {}
        return item if isinstance(item, dict) else {"suggested_value": item}

    def _validated_suggested_value(
        self,
        page,
        suggestion_type: ContentOptimizationSuggestionType,
        item: Dict[str, Any],
        internal_link_recs: List[Any],
    ) -> str:
        value = item.get("suggested_value")
        if suggestion_type == ContentOptimizationSuggestionType.seo_title:
            return self._validate_title(str(value or ""), page)
        if suggestion_type == ContentOptimizationSuggestionType.meta_description:
            return self._validate_meta(str(value or ""), page)
        if suggestion_type == ContentOptimizationSuggestionType.h1:
            return self._clean_text(str(value or self._topic(page)))
        if suggestion_type == ContentOptimizationSuggestionType.schema:
            return self._json_text(self._validate_schema(value, page))
        if suggestion_type == ContentOptimizationSuggestionType.faq:
            return self._json_text(self._validate_faq(value, page))
        if suggestion_type == ContentOptimizationSuggestionType.headings:
            return self._json_text(self._validate_list(value, [f"Key takeaways about {self._topic(page)}"]))
        if suggestion_type == ContentOptimizationSuggestionType.content_refresh:
            return self._json_text(self._validate_list(value, [f"Refresh this page with clearer details about {self._topic(page)}."]))
        if suggestion_type == ContentOptimizationSuggestionType.answer_block:
            answer = self._clean_text(str(value or ""))
            return answer or f"{self._topic(page)} gives visitors a concise overview of the page topic and related next steps."
        if suggestion_type == ContentOptimizationSuggestionType.internal_link_context:
            fallback = [
                f"Add a contextual internal link using anchor '{rec.suggested_anchor_text}' near related copy."
                for rec in internal_link_recs[:3]
            ]
            return self._json_text(self._validate_list(value, fallback))
        return self._clean_text(str(value or ""))

    def _validate_title(self, value: str, page) -> str:
        candidate = self._clean_text(value)
        if (
            len(candidate) < TITLE_MIN_LENGTH
            or len(candidate) > TITLE_MAX_LENGTH
            or self._is_spammy(candidate)
        ):
            candidate = f"{self._topic(page)} Guide and Page Overview"
        if len(candidate) < TITLE_MIN_LENGTH:
            candidate = f"{candidate} for Search Visitors"
        if len(candidate) > TITLE_MAX_LENGTH:
            candidate = self._truncate_words(candidate, TITLE_MAX_LENGTH)
        return candidate

    def _validate_meta(self, value: str, page) -> str:
        candidate = self._clean_text(value)
        if (
            len(candidate) < META_MIN_LENGTH
            or len(candidate) > META_MAX_LENGTH
            or self._is_spammy(candidate)
        ):
            candidate = (
                f"Explore {self._topic(page)} with concise details, helpful context, "
                "and related resources for visitors."
            )
        if len(candidate) > META_MAX_LENGTH:
            candidate = self._truncate_words(candidate, META_MAX_LENGTH)
        return candidate

    def _validate_schema(self, value: Any, page) -> Dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {}
        if not isinstance(value, dict):
            value = {}
        value.setdefault("@context", "https://schema.org")
        if value.get("@type") not in {"WebPage", "Article", "FAQPage", "CollectionPage", "AboutPage", "ProfilePage"}:
            value["@type"] = "WebPage"
        value.setdefault("name", self._validate_title(str(value.get("name") or page.title or ""), page))
        value.setdefault("url", page.url)
        if page.meta_description:
            value.setdefault("description", self._validate_meta(page.meta_description, page))
        return value

    def _validate_faq(self, value: Any, page) -> List[Dict[str, str]]:
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
            return faqs[:4]
        topic = self._topic(page)
        return [
            {"question": f"What is this page about?", "answer": f"This page gives visitors information about {topic}."},
            {"question": f"Where should visitors go next?", "answer": "Visitors should follow relevant internal links for related details."},
        ]

    def _validate_list(self, value: Any, fallback: List[str]) -> List[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            value = fallback
        cleaned = [self._clean_text(str(item)) for item in value if self._clean_text(str(item))]
        return cleaned[:6] or fallback

    def _current_value(
        self,
        page,
        suggestion_type: ContentOptimizationSuggestionType,
        internal_link_recs: List[Any],
    ) -> Optional[str]:
        if suggestion_type == ContentOptimizationSuggestionType.seo_title:
            return page.title
        if suggestion_type == ContentOptimizationSuggestionType.meta_description:
            return page.meta_description
        if suggestion_type == ContentOptimizationSuggestionType.h1:
            return self._json_text(page.h1 or [])
        if suggestion_type == ContentOptimizationSuggestionType.headings:
            return self._json_text({"h2": page.h2 or [], "h3": page.h3 or []})
        if suggestion_type == ContentOptimizationSuggestionType.schema:
            return self._json_text(page.schema_markup or {})
        if suggestion_type == ContentOptimizationSuggestionType.internal_link_context:
            return self._json_text([
                {"target_url": rec.target_url, "anchor": rec.suggested_anchor_text}
                for rec in internal_link_recs
            ])
        return None

    def _reason(
        self,
        suggestion_type: ContentOptimizationSuggestionType,
        item: Dict[str, Any],
        issue_types: set[str],
        page_score: Optional[Any],
    ) -> str:
        if suggestion_type == ContentOptimizationSuggestionType.seo_title:
            return "Improves the page title while keeping it within configured SEO title length guidance."
        if suggestion_type == ContentOptimizationSuggestionType.meta_description:
            return "Improves the search snippet while keeping it within configured meta description length guidance."
        if suggestion_type == ContentOptimizationSuggestionType.schema:
            return "Adds safe schema JSON-LD based on the crawled page topic and URL."
        llm_reason = self._clean_text(str(item.get("reason") or ""))
        if llm_reason:
            return llm_reason
        score = getattr(page_score, "score", None)
        issue_text = ", ".join(sorted(issue_types)) if issue_types else "general page optimization"
        return f"Suggested from crawl data, SEO score {score}, and audit signals: {issue_text}."

    def _priority_score(
        self,
        suggestion_type: ContentOptimizationSuggestionType,
        issue_types: set[str],
        page_score: Optional[Any],
        internal_link_recs: List[Any],
    ) -> float:
        score = 45.0
        if suggestion_type == ContentOptimizationSuggestionType.seo_title:
            score += 25 if issue_types.intersection({"missing_title", "title_too_short", "title_too_long", "duplicate_title"}) else 8
        elif suggestion_type == ContentOptimizationSuggestionType.meta_description:
            score += 25 if issue_types.intersection({"missing_meta_description", "meta_description_too_short", "meta_description_too_long", "duplicate_meta_description"}) else 8
        elif suggestion_type == ContentOptimizationSuggestionType.h1:
            score += 25
        elif suggestion_type == ContentOptimizationSuggestionType.schema:
            score += 20 if "missing_schema" in issue_types else 8
        elif suggestion_type == ContentOptimizationSuggestionType.content_refresh:
            score += 20 if "thin_content" in issue_types else 10
        elif suggestion_type == ContentOptimizationSuggestionType.internal_link_context:
            score += 20 if internal_link_recs else 0
        else:
            score += 10
        page_score_value = getattr(page_score, "score", None)
        if page_score_value is not None and page_score_value < 60:
            score += 10
        return round(min(100, score), 2)

    def _confidence_score(
        self,
        suggestion_type: ContentOptimizationSuggestionType,
        item: Dict[str, Any],
        suggested_value: str,
    ) -> float:
        try:
            confidence = float(item.get("confidence_score", 70))
        except (TypeError, ValueError):
            confidence = 70.0
        if suggestion_type in {
            ContentOptimizationSuggestionType.seo_title,
            ContentOptimizationSuggestionType.meta_description,
        } and self._is_spammy(suggested_value):
            confidence -= 25
        return round(max(0, min(100, confidence)), 2)

    def _content_hash(
        self,
        page,
        suggestion_type: ContentOptimizationSuggestionType,
        current_value: Optional[str],
        issue_types: set[str],
    ) -> str:
        seed = "|".join(
            [
                str(page.id),
                suggestion_type.value,
                current_value or "",
                str(page.word_count or 0),
                ",".join(sorted(issue_types)),
            ]
        ).lower()
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def _topic(self, page) -> str:
        h1_source = page.h1 or []
        if isinstance(h1_source, str):
            h1_source = [h1_source]
        h1_values = [str(value).strip() for value in h1_source if str(value).strip()]
        for value in h1_values + [page.title or ""]:
            if value and value.strip().lower() not in GENERIC_TITLES:
                return self._clean_text(value)
        generic_slug_parts = {"page", "pages", "tag", "tags", "category", "categories", "author", "authors", "login"}
        parts = [
            part for part in page.url.rstrip("/").split("/")
            if part and not part.isdigit() and part.lower() not in generic_slug_parts
        ]
        if parts:
            slug = parts[-1].replace("-", " ").replace("_", " ")
            return self._clean_text(slug.title())
        return "This Page"

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())

    def _truncate_words(self, value: str, max_length: int) -> str:
        value = self._clean_text(value)
        if len(value) <= max_length:
            return value
        truncated = value[:max_length].rsplit(" ", 1)[0].strip()
        return truncated or value[:max_length].strip()

    def _is_spammy(self, value: str) -> bool:
        words = [word.lower() for word in re.findall(r"[a-zA-Z]{3,}", value)]
        if not words:
            return False
        counts = defaultdict(int)
        for word in words:
            counts[word] += 1
        return any(count >= 4 for count in counts.values())

    def _json_text(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _average(self, values: List[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)
