"""Deterministic GEO/AEO scoring with optional local Ollama extraction."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.content_optimization import ContentOptimizationSuggestionType
from app.models.geo_aeo import (
    GeoAeoPageScore,
    GeoAeoRecommendation,
    GeoAeoRecommendationStatus,
    GeoAeoRecommendationType,
    GeoAeoRun,
    GeoAeoRunStatus,
)
from app.repositories.geo_aeo import GeoAeoRepository, RecommendationKey
from app.services.local_llm import LocalLLMError, LocalLLMService, OllamaRequestError

logger = structlog.get_logger(__name__)

LOW_SCORE_THRESHOLD = 65.0
VERY_LOW_SCORE_THRESHOLD = 45.0


class GeoAeoService:
    """Analyze crawled pages for AI-search readiness and answer-engine optimization."""

    def __init__(
        self,
        db: AsyncSession,
        llm_service: Optional[LocalLLMService] = None,
    ):
        self.db = db
        self.repository = GeoAeoRepository(db)
        self.llm_service = llm_service or LocalLLMService()

    async def start_analysis(self, crawl_id: UUID, tenant_id: UUID) -> GeoAeoRun:
        crawl = await self.repository.get_crawl(crawl_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")
        pages = await self.repository.list_crawl_pages(crawl_id)
        if not pages:
            raise ValueError("Crawl has no pages")

        run = await self.repository.create_run(crawl, model=settings.OLLAMA_DEFAULT_MODEL)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Created GEO/AEO analysis run", run_id=str(run.id), crawl_id=str(crawl_id))
        return run

    async def execute_analysis(self, run_id: UUID) -> GeoAeoRun:
        run = await self.repository.get_run(run_id)
        if not run:
            raise ValueError("GEO/AEO run not found")

        await self.repository.set_run_status(run, GeoAeoRunStatus.running, progress=5)
        await self.db.commit()

        try:
            crawl = await self.repository.get_crawl(run.crawl_id, run.tenant_id)
            if not crawl:
                raise ValueError("Crawl not found")

            pages = await self.repository.list_crawl_pages(run.crawl_id)
            audit_issues = await self.repository.list_audit_issues(run.crawl_id, run.tenant_id)
            seo_scores = await self.repository.list_seo_page_scores(run.crawl_id, run.tenant_id)
            crawl_links = await self.repository.list_internal_links(run.crawl_id)
            internal_link_recs = await self.repository.list_internal_link_recommendations(run.crawl_id, run.tenant_id)
            content_suggestions = await self.repository.list_content_suggestions(run.crawl_id, run.tenant_id)
            semantic_content = await self.repository.list_semantic_content(run.crawl_id, run.tenant_id)
            existing_keys = await self.repository.existing_recommendation_keys(run.crawl_id, run.tenant_id)

            context = self._build_context(
                pages=pages,
                audit_issues=audit_issues,
                seo_scores=seo_scores,
                crawl_links=crawl_links,
                internal_link_recs=internal_link_recs,
                content_suggestions=content_suggestions,
                semantic_content=semantic_content,
            )

            score_records: List[dict[str, Any]] = []
            recommendation_count = 0
            page_score_values: List[Dict[str, float]] = []

            for index, page in enumerate(pages, start=1):
                llm_payload = await self._extract_page_insights(page)
                score = self._score_page(run, page, context, llm_payload)
                recommendations = self._recommendation_records(run, page, context, score, llm_payload, existing_keys)

                score_records.append(score["record"])
                page_score_values.append(score["scores"])
                if recommendations:
                    recommendation_count += await self.repository.add_recommendations(recommendations)
                    for record in recommendations:
                        existing_keys.add((record["page_id"], record["recommendation_type"], record["content_hash"]))

                run.progress = min(95, 5 + int((index / max(len(pages), 1)) * 90))
                await self.db.commit()

            if score_records:
                await self.repository.add_page_scores(score_records)

            averages = self._run_averages(page_score_values)
            await self.repository.finish_run(
                run,
                total_pages=len(pages),
                total_recommendations=recommendation_count,
                average_geo_score=averages["geo_score"],
                average_aeo_score=averages["aeo_score"],
                average_citation_readiness_score=averages["citation_readiness_score"],
            )
            await self.repository.set_run_status(run, GeoAeoRunStatus.completed, progress=100)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info(
                "Completed GEO/AEO analysis run",
                run_id=str(run.id),
                pages=len(pages),
                recommendations=recommendation_count,
            )
            return run
        except Exception as exc:
            await self.repository.set_run_status(
                run,
                GeoAeoRunStatus.failed,
                error_message=str(exc),
                progress=100,
            )
            await self.db.commit()
            logger.error("GEO/AEO analysis failed", run_id=str(run.id), error=str(exc), exc_info=True)
            raise

    async def get_run_status(self, run_id: UUID, tenant_id: UUID) -> Optional[GeoAeoRun]:
        return await self.repository.get_run(run_id, tenant_id)

    async def get_page_score(self, page_id: UUID, tenant_id: UUID) -> Optional[GeoAeoPageScore]:
        return await self.repository.get_latest_page_score(page_id, tenant_id)

    async def list_recommendations(
        self,
        tenant_id: UUID,
        crawl_id: Optional[UUID] = None,
        page_id: Optional[UUID] = None,
        status: Optional[GeoAeoRecommendationStatus] = None,
        recommendation_type: Optional[GeoAeoRecommendationType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GeoAeoRecommendation]:
        return await self.repository.list_recommendations(
            tenant_id=tenant_id,
            crawl_id=crawl_id,
            page_id=page_id,
            status=status,
            recommendation_type=recommendation_type,
            limit=limit,
            offset=offset,
        )

    async def update_status(
        self,
        recommendation_id: UUID,
        tenant_id: UUID,
        status: GeoAeoRecommendationStatus,
    ) -> GeoAeoRecommendation:
        recommendation = await self.repository.get_recommendation(recommendation_id, tenant_id)
        if not recommendation:
            raise ValueError("Recommendation not found")
        recommendation = await self.repository.set_recommendation_status(recommendation, status)
        await self.db.commit()
        await self.db.refresh(recommendation)
        return recommendation

    async def summary(self, crawl_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        crawl = await self.repository.get_crawl(crawl_id, tenant_id)
        if not crawl:
            raise ValueError("Crawl not found")
        run = await self.repository.latest_run_for_crawl(crawl_id, tenant_id)
        page_scores = await self.repository.list_page_scores(
            tenant_id=tenant_id,
            crawl_id=crawl_id,
            run_id=run.id if run else None,
            limit=1000,
        )
        recommendations = await self.repository.list_recommendations(tenant_id=tenant_id, crawl_id=crawl_id, limit=1000)
        return {
            "crawl_id": crawl_id,
            "project_id": crawl.project_id,
            "run_id": run.id if run else None,
            "status": run.status if run else None,
            "total_pages": len(page_scores),
            "total_recommendations": len(recommendations),
            "average_geo_score": self._average([score.geo_score for score in page_scores]),
            "average_aeo_score": self._average([score.aeo_score for score in page_scores]),
            "average_citation_readiness_score": self._average([
                score.citation_readiness_score for score in page_scores
            ]),
            "average_answer_block_score": self._average([score.answer_block_score for score in page_scores]),
            "average_entity_clarity_score": self._average([score.entity_clarity_score for score in page_scores]),
            "average_schema_readiness_score": self._average([score.schema_readiness_score for score in page_scores]),
            "average_trust_signal_score": self._average([score.trust_signal_score for score in page_scores]),
            "average_topical_completeness_score": self._average([
                score.topical_completeness_score for score in page_scores
            ]),
            "recommendations_by_status": await self.repository.count_recommendations_by_status(crawl_id, tenant_id),
            "recommendations_by_type": await self.repository.count_recommendations_by_type(crawl_id, tenant_id),
        }

    async def _extract_page_insights(self, page) -> Dict[str, Any]:
        prompt = self._build_extraction_prompt(page)
        try:
            response = await self.llm_service.generate(
                prompt,
                model=settings.OLLAMA_DEFAULT_MODEL,
                options={"temperature": 0.1, "num_predict": 800},
            )
            payload = self._parse_llm_json(response.get("response", ""))
        except (LocalLLMError, OllamaRequestError, json.JSONDecodeError) as exc:
            logger.warning("Falling back to deterministic GEO/AEO extraction", page_id=str(page.id), error=str(exc))
            payload = {}
        return self._normalize_llm_payload(page, payload)

    def _build_context(
        self,
        pages: List[Any],
        audit_issues: List[Any],
        seo_scores: List[Any],
        crawl_links: List[Any],
        internal_link_recs: List[Any],
        content_suggestions: List[Any],
        semantic_content: List[Any],
    ) -> Dict[str, Any]:
        pages_by_id = {page.id: page for page in pages}
        url_to_page_id: Dict[str, UUID] = {}
        for page in pages:
            for url in {page.url, page.normalized_url, page.final_url}:
                if url:
                    url_to_page_id[self._url_key(url)] = page.id

        issues_by_page = defaultdict(list)
        for issue in audit_issues:
            if issue.crawl_page_id:
                issues_by_page[issue.crawl_page_id].append(issue)

        seo_scores_by_page = {}
        for score in seo_scores:
            seo_scores_by_page[score.crawl_page_id] = score

        inbound_counts = Counter()
        outbound_counts = Counter()
        for link in crawl_links:
            outbound_counts[link.source_page_id] += 1
            target_id = url_to_page_id.get(self._url_key(link.normalized_url or link.url))
            if target_id:
                inbound_counts[target_id] += 1
        if not crawl_links:
            for page in pages:
                for url in page.internal_link_urls or []:
                    target_id = url_to_page_id.get(self._url_key(url))
                    if target_id:
                        inbound_counts[target_id] += 1
                        outbound_counts[page.id] += 1

        internal_recs_by_page = defaultdict(list)
        for rec in internal_link_recs:
            internal_recs_by_page[rec.source_page_id].append(rec)
            internal_recs_by_page[rec.target_page_id].append(rec)

        content_suggestions_by_page = defaultdict(list)
        for suggestion in content_suggestions:
            content_suggestions_by_page[suggestion.page_id].append(suggestion)

        semantic_counts_by_page = Counter()
        semantic_types_by_page = defaultdict(set)
        for content in semantic_content:
            semantic_counts_by_page[content.crawl_page_id] += 1
            semantic_types_by_page[content.crawl_page_id].add(
                content.content_type.value if hasattr(content.content_type, "value") else str(content.content_type)
            )

        return {
            "pages_by_id": pages_by_id,
            "issues_by_page": issues_by_page,
            "seo_scores_by_page": seo_scores_by_page,
            "inbound_counts": inbound_counts,
            "outbound_counts": outbound_counts,
            "internal_recs_by_page": internal_recs_by_page,
            "content_suggestions_by_page": content_suggestions_by_page,
            "semantic_counts_by_page": semantic_counts_by_page,
            "semantic_types_by_page": semantic_types_by_page,
        }

    def _score_page(
        self,
        run: GeoAeoRun,
        page,
        context: Dict[str, Any],
        llm_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        issues = context["issues_by_page"][page.id]
        issue_types = {issue.issue_type for issue in issues}
        seo_score = context["seo_scores_by_page"].get(page.id)
        content_suggestions = context["content_suggestions_by_page"][page.id]
        semantic_count = context["semantic_counts_by_page"][page.id]
        semantic_types = context["semantic_types_by_page"][page.id]
        internal_recs = context["internal_recs_by_page"][page.id]
        inbound_count = int(context["inbound_counts"][page.id])
        outbound_count = int(context["outbound_counts"][page.id] or page.internal_links or 0)

        entities = self._entities(page, llm_payload)
        claims = self._claims(page, llm_payload)
        text = self._clean_text(page.text_content or "")
        word_count = int(page.word_count or len(text.split()))
        heading_count = self._heading_count(page)
        qa_count = self._question_answer_count(text, content_suggestions)
        answer_block_candidates = self._answer_block_candidates(
            text,
            content_suggestions,
            llm_payload,
            include_llm=False,
        )

        factual_density_score = self._score_factual_density(claims, word_count)
        structured_claims_score = self._score_structured_claims(claims, heading_count)
        answer_block_score = self._score_answer_blocks(answer_block_candidates, content_suggestions)
        faq_coverage_score = self._score_faq_coverage(qa_count, content_suggestions)
        schema_readiness_score = self._score_schema(page, content_suggestions, issue_types)
        trust_signal_score = self._score_trust(page, text, issue_types)
        entity_clarity_score = self._score_entity_clarity(page, entities)
        topical_completeness_score = self._score_topical_completeness(
            page,
            word_count,
            heading_count,
            semantic_count,
            issue_types,
        )
        semantic_clarity_score = self._score_semantic_clarity(page, semantic_count, semantic_types, entities)
        internal_link_support_score = self._score_internal_link_support(
            inbound_count,
            outbound_count,
            internal_recs,
            issue_types,
        )
        citation_readiness_score = self._weighted_average(
            [
                (factual_density_score, 0.28),
                (structured_claims_score, 0.18),
                (trust_signal_score, 0.18),
                (schema_readiness_score, 0.15),
                (entity_clarity_score, 0.13),
                (topical_completeness_score, 0.08),
            ]
        )
        definition_style_score = self._score_definition_style(text, page)
        extractability_score = self._score_extractability(page, text, heading_count, issue_types)

        geo_score = self._weighted_average(
            [
                (entity_clarity_score, 0.20),
                (topical_completeness_score, 0.18),
                (semantic_clarity_score, 0.16),
                (citation_readiness_score, 0.16),
                (schema_readiness_score, 0.12),
                (internal_link_support_score, 0.10),
                (extractability_score, 0.08),
            ]
        )
        aeo_score = self._weighted_average(
            [
                (answer_block_score, 0.24),
                (faq_coverage_score, 0.18),
                (definition_style_score, 0.16),
                (schema_readiness_score, 0.14),
                (entity_clarity_score, 0.12),
                (extractability_score, 0.10),
                (internal_link_support_score, 0.06),
            ]
        )

        existing_seo_score = getattr(seo_score, "score", None)
        if existing_seo_score is not None:
            geo_score = round((geo_score * 0.9) + (float(existing_seo_score) * 0.1), 2)
            aeo_score = round((aeo_score * 0.9) + (float(existing_seo_score) * 0.1), 2)

        scores = {
            "geo_score": self._clamp(geo_score),
            "aeo_score": self._clamp(aeo_score),
            "citation_readiness_score": self._clamp(citation_readiness_score),
            "answer_block_score": self._clamp(answer_block_score),
            "entity_clarity_score": self._clamp(entity_clarity_score),
            "schema_readiness_score": self._clamp(schema_readiness_score),
            "trust_signal_score": self._clamp(trust_signal_score),
            "topical_completeness_score": self._clamp(topical_completeness_score),
        }
        breakdown = {
            **scores,
            "factual_density_score": self._clamp(factual_density_score),
            "structured_claims_score": self._clamp(structured_claims_score),
            "faq_coverage_score": self._clamp(faq_coverage_score),
            "semantic_clarity_score": self._clamp(semantic_clarity_score),
            "internal_link_support_score": self._clamp(internal_link_support_score),
            "definition_style_score": self._clamp(definition_style_score),
            "extractability_score": self._clamp(extractability_score),
            "question_answer_coverage": qa_count,
            "inbound_internal_links": inbound_count,
            "outbound_internal_links": outbound_count,
            "semantic_indexed_units": semantic_count,
            "seo_score": existing_seo_score,
        }

        return {
            "scores": scores,
            "breakdown": breakdown,
            "entities": entities,
            "claims": claims,
            "answer_blocks": answer_block_candidates,
            "record": {
                "run_id": run.id,
                "tenant_id": run.tenant_id,
                "project_id": run.project_id,
                "crawl_id": run.crawl_id,
                "page_id": page.id,
                "url": page.url,
                **scores,
                "score_breakdown": breakdown,
                "extracted_entities": entities,
                "extracted_claims": claims,
                "evidence": {
                    "audit_issue_types": sorted(issue_types),
                    "word_count": word_count,
                    "heading_count": heading_count,
                    "schema_types": page.schema_types or [],
                    "content_suggestions": [
                        self._enum_value(suggestion.suggestion_type) for suggestion in content_suggestions
                    ],
                    "local_llm_model": run.model,
                },
            },
        }

    def _recommendation_records(
        self,
        run: GeoAeoRun,
        page,
        context: Dict[str, Any],
        score: Dict[str, Any],
        llm_payload: Dict[str, Any],
        existing_keys: set[RecommendationKey],
    ) -> List[Dict[str, Any]]:
        breakdown = score["breakdown"]
        entities = score["entities"]
        claims = score["claims"]
        answer_blocks = score["answer_blocks"]
        content_suggestions = context["content_suggestions_by_page"][page.id]
        internal_recs = context["internal_recs_by_page"][page.id]
        issue_types = {issue.issue_type for issue in context["issues_by_page"][page.id]}

        candidates: List[Dict[str, Any]] = []
        if breakdown["answer_block_score"] < LOW_SCORE_THRESHOLD:
            candidates.append(self._candidate(
                GeoAeoRecommendationType.answer_block,
                self._answer_block_text(page, llm_payload, answer_blocks),
                "Page lacks a concise extractable answer block for answer engines.",
                breakdown["answer_block_score"],
            ))
        if breakdown["faq_coverage_score"] < LOW_SCORE_THRESHOLD:
            candidates.append(self._candidate(
                GeoAeoRecommendationType.faq,
                f"Add 2-4 focused FAQ questions that answer common questions about {self._topic(page)}.",
                "Question-answer coverage is thin or only present as generated suggestions.",
                breakdown["faq_coverage_score"],
            ))
        if score["scores"]["schema_readiness_score"] < LOW_SCORE_THRESHOLD:
            candidates.append(self._candidate(
                GeoAeoRecommendationType.schema,
                "Add WebPage or FAQPage JSON-LD that reflects the visible page topic and canonical URL.",
                "Schema helps AI and search systems identify the page type and extract structured facts.",
                score["scores"]["schema_readiness_score"],
            ))
        if score["scores"]["entity_clarity_score"] < LOW_SCORE_THRESHOLD:
            entity_hint = ", ".join(entities[:3]) if entities else self._topic(page)
            candidates.append(self._candidate(
                GeoAeoRecommendationType.entity_clarity,
                f"Clarify the primary entity near the top of the page: {entity_hint}.",
                "Title, H1, and body copy do not make the main entity explicit enough.",
                score["scores"]["entity_clarity_score"],
            ))
        if breakdown["factual_density_score"] < LOW_SCORE_THRESHOLD or breakdown["structured_claims_score"] < LOW_SCORE_THRESHOLD:
            claim_hint = self._claim_text(page, claims)
            candidates.append(self._candidate(
                GeoAeoRecommendationType.factual_claims,
                claim_hint,
                "AI summaries need clear, verifiable claims rather than only navigational or thin copy.",
                min(breakdown["factual_density_score"], breakdown["structured_claims_score"]),
            ))
        if score["scores"]["trust_signal_score"] < LOW_SCORE_THRESHOLD:
            candidates.append(self._candidate(
                GeoAeoRecommendationType.trust_signal,
                "Add visible author, company, source, or contact context where appropriate for the page.",
                "Trust signals are weak, which lowers citation-readiness and AI extraction confidence.",
                score["scores"]["trust_signal_score"],
            ))
        if breakdown["internal_link_support_score"] < LOW_SCORE_THRESHOLD and internal_recs:
            candidates.append(self._candidate(
                GeoAeoRecommendationType.internal_link_support,
                self._internal_link_text(internal_recs),
                "Internal link recommendations indicate the page needs more contextual support.",
                breakdown["internal_link_support_score"],
            ))
        if score["scores"]["topical_completeness_score"] < LOW_SCORE_THRESHOLD:
            candidates.append(self._candidate(
                GeoAeoRecommendationType.topical_gap,
                f"Expand the page with concise sections covering definitions, examples, and next steps for {self._topic(page)}.",
                "Topical coverage is thin based on word count, headings, semantic units, and audit signals.",
                score["scores"]["topical_completeness_score"],
            ))

        records: List[Dict[str, Any]] = []
        for candidate in candidates:
            text = self._clean_text(candidate["recommendation_text"])
            if not text:
                continue
            content_hash = self._content_hash(page, candidate["recommendation_type"], text, issue_types)
            key = (page.id, candidate["recommendation_type"], content_hash)
            if key in existing_keys:
                continue
            records.append(
                {
                    "run_id": run.id,
                    "tenant_id": run.tenant_id,
                    "project_id": run.project_id,
                    "crawl_id": run.crawl_id,
                    "page_id": page.id,
                    "recommendation_type": candidate["recommendation_type"],
                    "recommendation_text": text,
                    "reason": candidate["reason"],
                    "priority_score": candidate["priority_score"],
                    "confidence_score": candidate["confidence_score"],
                    "status": GeoAeoRecommendationStatus.suggested,
                    "content_hash": content_hash,
                    "evidence": {
                        "url": page.url,
                        "geo_score": score["scores"]["geo_score"],
                        "aeo_score": score["scores"]["aeo_score"],
                        "audit_issue_types": sorted(issue_types),
                        "content_optimization_suggestion_types": [
                            self._enum_value(suggestion.suggestion_type) for suggestion in content_suggestions
                        ],
                    },
                }
            )
        return records

    def _candidate(
        self,
        recommendation_type: GeoAeoRecommendationType,
        recommendation_text: str,
        reason: str,
        source_score: float,
    ) -> Dict[str, Any]:
        deficit = max(0.0, 100.0 - float(source_score or 0))
        return {
            "recommendation_type": recommendation_type,
            "recommendation_text": recommendation_text,
            "reason": reason,
            "priority_score": round(min(100.0, 45.0 + deficit * 0.55), 2),
            "confidence_score": round(max(50.0, min(95.0, 90.0 - deficit * 0.25)), 2),
        }

    def _build_extraction_prompt(self, page) -> str:
        text_preview = self._clean_text(page.text_content or "")[:1800]
        return (
            "You are a local GEO/AEO extraction assistant running inside a self-hosted app. "
            "Return only valid JSON. Do not invent facts that are not in the supplied page text.\n\n"
            "JSON shape:\n"
            "{\n"
            '  "entities": ["entity or topic"],\n'
            '  "factual_claims": ["short factual claim grounded in the text"],\n'
            '  "answer_block": "40-60 word direct answer based only on the page text"\n'
            "}\n\n"
            f"URL: {page.url}\n"
            f"Title: {page.title or ''}\n"
            f"Meta description: {page.meta_description or ''}\n"
            f"H1: {json.dumps(page.h1 or [])}\n"
            f"H2: {json.dumps(page.h2 or [])}\n"
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

    def _normalize_llm_payload(self, page, payload: Dict[str, Any]) -> Dict[str, Any]:
        entities = self._validate_string_list(payload.get("entities"), fallback=self._regex_entities(page))
        claims = self._validate_string_list(payload.get("factual_claims"), fallback=self._regex_claims(page))
        answer_block = self._clean_text(str(payload.get("answer_block") or ""))
        if len(answer_block.split()) < 8:
            answer_block = self._fallback_answer_block(page)
        return {
            "entities": entities[:12],
            "factual_claims": claims[:12],
            "answer_block": answer_block,
        }

    def _entities(self, page, llm_payload: Dict[str, Any]) -> List[str]:
        values = llm_payload.get("entities") or []
        merged = list(dict.fromkeys([*values, *self._regex_entities(page)]))
        return [value for value in merged if value][:12]

    def _claims(self, page, llm_payload: Dict[str, Any]) -> List[str]:
        values = llm_payload.get("factual_claims") or []
        merged = list(dict.fromkeys([*values, *self._regex_claims(page)]))
        return [value for value in merged if value][:12]

    def _score_entity_clarity(self, page, entities: List[str]) -> float:
        score = 15.0
        title = self._clean_text(page.title or "")
        h1_values = self._headings(page, ["h1"])
        topic = self._topic(page).lower()
        if title:
            score += 20
        if h1_values:
            score += 18
        if title and h1_values and any(self._overlap(title, h1) for h1 in h1_values):
            score += 15
        if entities:
            score += min(22, len(entities) * 5)
        if topic and topic != "this page" and (topic in title.lower() or any(topic in h1.lower() for h1 in h1_values)):
            score += 10
        return score

    def _score_factual_density(self, claims: List[str], word_count: int) -> float:
        if word_count <= 0:
            return 15.0
        claims_per_500_words = len(claims) / max(word_count / 500, 0.5)
        return 25 + min(70, claims_per_500_words * 16)

    def _score_structured_claims(self, claims: List[str], heading_count: int) -> float:
        score = 20 + min(45, len(claims) * 8)
        if heading_count >= 2:
            score += 18
        elif heading_count == 1:
            score += 8
        if any(re.search(r"\b(is|are|means|includes|offers|provides|contains)\b", claim, re.I) for claim in claims):
            score += 12
        return score

    def _score_answer_blocks(self, answer_blocks: List[str], content_suggestions: List[Any]) -> float:
        score = 20.0
        if answer_blocks:
            best_words = max(len(block.split()) for block in answer_blocks)
            if 25 <= best_words <= 80:
                score += 45
            elif 12 <= best_words < 25:
                score += 28
            elif best_words > 80:
                score += 22
        if self._has_content_suggestion(content_suggestions, "answer_block"):
            score += 8
        return score

    def _score_faq_coverage(self, qa_count: int, content_suggestions: List[Any]) -> float:
        score = 18 + min(50, qa_count * 18)
        if self._has_content_suggestion(content_suggestions, "faq"):
            score += 18
        return score

    def _score_schema(self, page, content_suggestions: List[Any], issue_types: set[str]) -> float:
        score = 20.0
        if page.has_schema_markup or page.schema_markup:
            score += 55
        if page.schema_types:
            score += min(15, len(page.schema_types) * 5)
        if self._has_content_suggestion(content_suggestions, "schema"):
            score += 15
        if "missing_schema" in issue_types or "missing_schema_markup" in issue_types:
            score -= 20
        return score

    def _score_trust(self, page, text: str, issue_types: set[str]) -> float:
        score = 35.0
        trust_terms = re.findall(r"\b(author|about|contact|company|team|source|profile|copyright|privacy|editorial)\b", text, re.I)
        score += min(25, len(set(term.lower() for term in trust_terms)) * 6)
        if "/author/" in page.url.lower():
            score += 18
        if page.canonical_url:
            score += 10
        if page.has_og_tags:
            score += 6
        if page.noindex or "noindex_pages" in issue_types:
            score -= 25
        return score

    def _score_topical_completeness(
        self,
        page,
        word_count: int,
        heading_count: int,
        semantic_count: int,
        issue_types: set[str],
    ) -> float:
        score = 15.0
        if word_count >= 800:
            score += 35
        elif word_count >= 400:
            score += 28
        elif word_count >= 150:
            score += 18
        elif word_count >= 60:
            score += 10
        score += min(22, heading_count * 4)
        score += min(18, semantic_count * 2)
        if page.meta_description:
            score += 5
        if "thin_content" in issue_types:
            score -= 25
        return score

    def _score_semantic_clarity(self, page, semantic_count: int, semantic_types: Iterable[str], entities: List[str]) -> float:
        score = 30.0
        if semantic_count:
            score += min(35, semantic_count * 3)
        if {"title", "heading", "chunk"}.intersection(set(semantic_types)):
            score += 15
        if entities:
            score += min(15, len(entities) * 3)
        if page.content_hash:
            score += 5
        return score

    def _score_internal_link_support(
        self,
        inbound_count: int,
        outbound_count: int,
        internal_recs: List[Any],
        issue_types: set[str],
    ) -> float:
        score = 25.0
        score += min(28, inbound_count * 10)
        score += min(20, outbound_count * 4)
        if internal_recs:
            score += 10
        if inbound_count == 0:
            score -= 15
        if "orphan_pages" in issue_types or "weak_internal_link_depth" in issue_types:
            score -= 15
        return score

    def _score_definition_style(self, text: str, page) -> float:
        score = 25.0
        topic = re.escape(self._topic(page))
        patterns = [
            rf"\b{topic}\b\s+(is|are|means|refers to)\b",
            r"\bwhat is\b",
            r"\bdefinition\b",
            r"\bin short\b",
        ]
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            score += 45
        first_sentence = self._first_sentence(text)
        if 12 <= len(first_sentence.split()) <= 45:
            score += 18
        return score

    def _score_extractability(self, page, text: str, heading_count: int, issue_types: set[str]) -> float:
        score = 30.0
        if page.title:
            score += 12
        if page.meta_description:
            score += 10
        if heading_count:
            score += 12
        if len(text.split()) >= 80:
            score += 12
        if page.has_schema_markup or page.schema_markup:
            score += 12
        if page.noindex:
            score -= 25
        if issue_types.intersection({"missing_title", "missing_h1", "missing_meta_description"}):
            score -= 10
        return score

    def _recommendation_priority_from_score(self, score: float) -> float:
        return round(min(100.0, 45.0 + max(0.0, 100.0 - score) * 0.55), 2)

    def _answer_block_candidates(
        self,
        text: str,
        content_suggestions: List[Any],
        llm_payload: Dict[str, Any],
        include_llm: bool = True,
    ) -> List[str]:
        candidates = []
        if include_llm and llm_payload.get("answer_block"):
            candidates.append(llm_payload["answer_block"])
        if include_llm:
            candidates.extend(self._content_suggestion_values(content_suggestions, "answer_block"))
        first = self._first_sentence(text)
        if first:
            candidates.append(first)
        return [self._clean_text(candidate) for candidate in candidates if self._clean_text(candidate)]

    def _question_answer_count(self, text: str, content_suggestions: List[Any]) -> int:
        count = len(re.findall(r"\?", text or ""))
        for value in self._content_suggestion_values(content_suggestions, "faq"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                count += len([item for item in parsed if isinstance(item, dict) and item.get("question")])
        return count

    def _answer_block_text(self, page, llm_payload: Dict[str, Any], answer_blocks: List[str]) -> str:
        answer = self._clean_text(llm_payload.get("answer_block") or "")
        if not answer and answer_blocks:
            answer = answer_blocks[0]
        if not answer:
            answer = self._fallback_answer_block(page)
        return f"Add a concise answer block near the top: {answer}"

    def _claim_text(self, page, claims: List[str]) -> str:
        if claims:
            return f"Add a short evidence-led section with claims such as: {claims[0]}"
        return f"Add 2-3 clear factual claims that explain what {self._topic(page)} is, who it helps, and why it matters."

    def _internal_link_text(self, internal_recs: List[Any]) -> str:
        rec = internal_recs[0]
        target = getattr(rec, "target_url", None) or getattr(rec, "source_url", "")
        anchor = getattr(rec, "suggested_anchor_text", "related page")
        return f"Add contextual internal support using anchor '{anchor}' toward {target}."

    def _content_suggestion_values(self, suggestions: List[Any], suggestion_type: str) -> List[str]:
        values = []
        for suggestion in suggestions:
            if self._enum_value(suggestion.suggestion_type) == suggestion_type:
                values.append(suggestion.suggested_value or "")
        return values

    def _has_content_suggestion(self, suggestions: List[Any], suggestion_type: str) -> bool:
        return any(self._enum_value(suggestion.suggestion_type) == suggestion_type for suggestion in suggestions)

    def _heading_count(self, page) -> int:
        return len(self._headings(page, ["h1", "h2", "h3", "h4", "h5", "h6"]))

    def _headings(self, page, names: List[str]) -> List[str]:
        values: List[str] = []
        for name in names:
            raw = getattr(page, name, None) or []
            if isinstance(raw, str):
                raw = [raw]
            values.extend([self._clean_text(str(item)) for item in raw if self._clean_text(str(item))])
        return values

    def _regex_entities(self, page) -> List[str]:
        seeds = [page.title or "", *self._headings(page, ["h1", "h2"])]
        text = " ".join(seeds + [self._clean_text(page.text_content or "")[:1000]])
        candidates = re.findall(r"\b(?:[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+){0,3})\b", text)
        stopwords = {"The", "This", "That", "It", "And", "For", "With", "Login", "Next", "Previous"}
        return list(dict.fromkeys([item for item in candidates if item not in stopwords]))[:10]

    def _regex_claims(self, page) -> List[str]:
        text = self._clean_text(page.text_content or "")
        sentences = re.split(r"(?<=[.!?])\s+", text)
        claim_patterns = re.compile(r"\b(is|are|was|were|means|includes|contains|provides|offers|helps|shows|lists)\b", re.I)
        claims = [
            sentence.strip()
            for sentence in sentences
            if 8 <= len(sentence.split()) <= 35 and claim_patterns.search(sentence)
        ]
        return claims[:8]

    def _fallback_answer_block(self, page) -> str:
        topic = self._topic(page)
        meta = self._clean_text(page.meta_description or "")
        if meta:
            return meta
        return f"{topic} gives visitors a concise overview of the page topic and related details from the crawled site."

    def _validate_string_list(self, value: Any, fallback: List[str]) -> List[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            value = fallback
        cleaned = [self._clean_text(str(item)) for item in value if self._clean_text(str(item))]
        return cleaned or fallback

    def _content_hash(
        self,
        page,
        recommendation_type: GeoAeoRecommendationType,
        recommendation_text: str,
        issue_types: set[str],
    ) -> str:
        seed = "|".join([
            str(page.id),
            recommendation_type.value,
            recommendation_text,
            str(page.word_count or 0),
            ",".join(sorted(issue_types)),
        ]).lower()
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def _run_averages(self, score_values: List[Dict[str, float]]) -> Dict[str, float]:
        return {
            "geo_score": self._average([item["geo_score"] for item in score_values]),
            "aeo_score": self._average([item["aeo_score"] for item in score_values]),
            "citation_readiness_score": self._average([
                item["citation_readiness_score"] for item in score_values
            ]),
        }

    def _weighted_average(self, values: List[tuple[float, float]]) -> float:
        total_weight = sum(weight for _, weight in values) or 1.0
        return round(sum(self._clamp(value) * weight for value, weight in values) / total_weight, 2)

    def _average(self, values: List[float]) -> float:
        if not values:
            return 0.0
        return round(sum(float(value or 0) for value in values) / len(values), 2)

    def _clamp(self, value: float) -> float:
        return round(max(0.0, min(100.0, float(value or 0))), 2)

    def _topic(self, page) -> str:
        headings = self._headings(page, ["h1"])
        for value in [*headings, page.title or ""]:
            cleaned = self._clean_text(value)
            if cleaned and cleaned.lower() not in {"home", "homepage", "untitled", "quotes to scrape", "login"}:
                return cleaned
        generic_slug_parts = {"page", "pages", "tag", "tags", "category", "categories", "author", "authors", "login"}
        parts = [
            part for part in page.url.rstrip("/").split("/")
            if part and not part.isdigit() and part.lower() not in generic_slug_parts
        ]
        if parts:
            return self._clean_text(parts[-1].replace("-", " ").replace("_", " ").title())
        return "This Page"

    def _first_sentence(self, text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", self._clean_text(text))
        return sentences[0] if sentences and sentences[0] else ""

    def _overlap(self, left: str, right: str) -> bool:
        left_words = set(re.findall(r"[a-z0-9]{3,}", left.lower()))
        right_words = set(re.findall(r"[a-z0-9]{3,}", right.lower()))
        return bool(left_words and right_words and left_words.intersection(right_words))

    def _url_key(self, url: str) -> str:
        return (url or "").split("#", 1)[0].rstrip("/").lower()

    def _enum_value(self, value: Any) -> str:
        return value.value if hasattr(value, "value") else str(value)

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip())
