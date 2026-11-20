"""Local-LLM-powered content optimization suggestions."""
from __future__ import annotations

import asyncio

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


class ContentRunAlreadyRunning(RuntimeError):
    """Another generation for this crawl has not finished yet.

    Its own exception type so the orchestrator can tell "someone already
    started this" from a genuine failure, and report it as such instead of
    marking the stage broken.
    """


class UnusableModelResponse(RuntimeError):
    """The model answered, but the answer could not be read as suggestions.

    Deliberately not an ``OllamaRequestError``. That type covers an unreachable
    or erroring Ollama as well as a malformed reply, and the two call for
    opposite handling: a model that is down should fail the run loudly, while a
    single reply this service cannot parse is an ordinary event to log and step
    past. Collapsing them meant either one page could kill the run, or an
    entirely dead Ollama could produce a "completed" run with no suggestions in
    it — both of which this stage has done.
    """


TITLE_MIN_LENGTH = 30
TITLE_MAX_LENGTH = 60
META_MIN_LENGTH = 50
META_MAX_LENGTH = 160
GENERIC_TITLES = {"home", "homepage", "untitled", "quotes to scrape", "login"}

#: Below this, a page gives the model nothing to work from. The prompt is built
#: out of the page's own text, so asking about an empty page invites invention,
#: and inventing content is the one thing this product must never do.
LLM_MIN_WORD_COUNT = 50

#: Enough substance for an answer engine to quote, and for subheadings to be
#: worth suggesting. Below it, an FAQ or answer block would be padding.
AEO_MIN_WORD_COUNT = 300

#: What the audit calls thin. Kept in step with it so the two cannot disagree
#: about whether a page needs more content.
THIN_CONTENT_WORDS = 300


#: The JSON line asked of the model for each suggestion type.
#:
#: The prompt used to request all nine on every page and cap the reply at 1200
#: tokens. ``_suggestion_records`` only ever reads the types it is given, so the
#: rest were generated and thrown away — and on a CPU-only Ollama the reply
#: length *is* the runtime: a 3B model emits a few tokens a second, so asking
#: for nine sections cost minutes a page. Asking only for what will be stored is
#: the same output for a fraction of the time.
#: Placeholders are written as <angle-bracketed slots> on purpose. Spelled as
#: plain descriptive text — "50-160 char meta description" — a 3B model copies
#: them back verbatim instead of writing anything: measured on six real pages,
#: three returned the placeholder itself as the suggestion. Those then failed the
#: length check and were replaced with canned filler, so the page got a
#: meaningless description and nobody could tell the model had never answered.
SUGGESTION_JSON_SHAPES: Dict[str, str] = {
    # No "reason" on these three: `_reason()` returns a fixed sentence for them
    # and never reads what the model wrote. Asking for it anyway meant paying to
    # generate a field that was discarded on arrival — on a CPU-only box, output
    # tokens are the runtime, so this was pure cost.
    "seo_title": '  "seo_title": {"suggested_value": "<your title here, 30-60 characters>", "confidence_score": 0-100}',
    "meta_description": '  "meta_description": {"suggested_value": "<your description here, 50-160 characters>", "confidence_score": 0-100}',
    "schema": '  "schema": {"suggested_value": {"@context": "https://schema.org", "@type": "WebPage"}, "confidence_score": 0-100}',
    # The rest do surface the model's reason, so it is asked for — but bounded.
    # Left open it writes a paragraph nobody reads in full.
    "h1": '  "h1": {"suggested_value": "<your single H1 here>", "reason": "<why, under 12 words>", "confidence_score": 0-100}',
    "headings": '  "headings": {"suggested_value": ["<your H2 or H3 here>"], "reason": "<why, under 12 words>", "confidence_score": 0-100}',
    # Exactly two pairs. Left unbounded the model writes four or five, which was
    # the single largest block of output on a typical page.
    "faq": '  "faq": {"suggested_value": [{"question": "<question 1>", "answer": "<answer 1>"}, {"question": "<question 2>", "answer": "<answer 2>"}], "reason": "<why, under 12 words>", "confidence_score": 0-100}',
    "content_refresh": '  "content_refresh": {"suggested_value": ["<your recommendation>"], "reason": "<why, under 12 words>", "confidence_score": 0-100}',
    "answer_block": '  "answer_block": {"suggested_value": "<your 40-60 word direct answer>", "reason": "<why, under 12 words>", "confidence_score": 0-100}',
    "internal_link_context": '  "internal_link_context": {"suggested_value": ["<sentence showing where the link goes>"], "reason": "<why, under 12 words>", "confidence_score": 0-100}',
}

#: Output budget per requested section, and the floor below which even a
#: one-field reply would be truncated mid-JSON and fail to parse.
TOKENS_PER_SUGGESTION = 170
MIN_PREDICT_TOKENS = 320


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

        # Refuse to start a second generation for the same crawl while one is
        # still going. Two runs over the same pages do not finish any sooner —
        # they share one CPU-bound model, so each takes twice as long — and they
        # race to write the same suggestions. This happened the moment a resume
        # was triggered twice: both workers ground away at the same 171 pages,
        # the stage looked stalled, and the dashboard showed a stage that kept
        # resetting itself.
        in_flight = await self.repository.find_active_run(crawl_id, tenant_id)
        if in_flight is not None:
            raise ContentRunAlreadyRunning(
                f"A content run for this crawl is already in progress "
                f"({in_flight.progress or 0}% complete). Wait for it to finish, "
                "or let it fail before starting another."
            )

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
            analysed_count = 0
            skipped: Dict[str, int] = defaultdict(int)

            # Decide what every page needs before generating anything. The model
            # is the whole cost of this stage; everything else here is arithmetic.
            planned: List[tuple[Any, List[ContentOptimizationSuggestionType]]] = []
            for page in pages:
                issue_types = {issue.issue_type for issue in issues_by_page[page.id]}
                link_recs = link_recs_by_page[page.id]
                pending_types = self._pending_types(page, issue_types, link_recs, existing_keys)
                skip_reason = self._skip_reason(page, issue_types, link_recs, pending_types)
                if skip_reason:
                    skipped[skip_reason] += 1
                    continue
                planned.append((page, pending_types))

            total_to_analyse = len(planned)
            await self._publish_progress(run, 5, analysed_count, total_to_analyse, created_count)

            # Generate in small concurrent batches. Measured on this hardware:
            # with Ollama pinned to 4 cores, concurrency made throughput *worse*
            # (2.12 -> 1.67 pages/min at 3 at a time) because one generation
            # already saturates every core. With 8 cores there is headroom and
            # two at a time is the best of the measured options (2.63 -> 2.94),
            # while four is worse again. Hence a small, configurable degree
            # rather than "as parallel as possible".
            #
            # Only the model calls overlap. Everything touching the database
            # happens one at a time below, because an AsyncSession is a single
            # connection and concurrent use corrupts it.
            batch_size = max(1, int(settings.CONTENT_LLM_CONCURRENCY))

            for offset in range(0, total_to_analyse, batch_size):
                batch = planned[offset:offset + batch_size]

                payloads = await asyncio.gather(
                    *(
                        self._generate_page_payload(
                            page,
                            issues_by_page[page.id],
                            scores_by_page.get(page.id),
                            link_recs_by_page[page.id],
                            project_context_text,
                            requested_types=pending_types,
                        )
                        for page, pending_types in batch
                    ),
                    return_exceptions=True,
                )

                for (page, pending_types), payload in zip(batch, payloads):
                    if isinstance(payload, UnusableModelResponse):
                        # One page's reply is not the run. A local model
                        # occasionally returns something that will not parse, and
                        # aborting here threw away every page already generated —
                        # which is how a stage that had done sixty pages of real
                        # work ended up recording nothing at all. The page is
                        # counted and skipped; the next run picks it up, because
                        # its suggestions are still missing and the filter sees
                        # that.
                        skipped["llm_unusable_response"] += 1
                        logger.warning(
                            "Content optimization skipped a page",
                            run_id=str(run.id),
                            url=getattr(page, "url", None),
                            error=str(payload),
                        )
                        continue
                    if isinstance(payload, BaseException):
                        # Anything else — an unreachable model, a cancelled task —
                        # is not this page's problem and must stop the run rather
                        # than be silently absorbed into a "completed" result.
                        raise payload

                    analysed_count += 1
                    records = self._suggestion_records(
                        run=run,
                        page=page,
                        payload=payload,
                        audit_issues=issues_by_page[page.id],
                        page_score=scores_by_page.get(page.id),
                        internal_link_recs=link_recs_by_page[page.id],
                        existing_keys=existing_keys,
                        target_types=pending_types,
                    )
                    if records:
                        created_count += await self.repository.add_suggestions(records)
                        for record in records:
                            existing_keys.add(
                                (record["page_id"], record["suggestion_type"], record["content_hash"])
                            )

                progress = 5 + int((min(offset + batch_size, total_to_analyse) / max(total_to_analyse, 1)) * 90)
                await self._publish_progress(run, progress, analysed_count, total_to_analyse, created_count)

            logger.info(
                "Content optimization page selection",
                run_id=str(run.id),
                pages_crawled=len(pages),
                pages_analysed=analysed_count,
                pages_skipped=dict(skipped),
            )
            # total_pages records what was analysed, not what was crawled: it is
            # the denominator for "suggestions per page" everywhere downstream,
            # and counting skipped pages in it would understate the stage.
            await self.repository.finish_run(run, total_pages=analysed_count, total_suggestions=created_count)
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
        requested_types: Optional[List[ContentOptimizationSuggestionType]] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(
            page,
            audit_issues,
            page_score,
            internal_link_recs,
            project_context_text,
            requested_types=requested_types,
        )
        # Budget the reply to what was asked for. On a CPU-only Ollama the token
        # count is the runtime, so a flat 1200 made a page needing one new title
        # cost the same as a page needing all nine sections.
        sections = len(requested_types) if requested_types else len(SUGGESTION_JSON_SHAPES)
        num_predict = max(MIN_PREDICT_TOKENS, sections * TOKENS_PER_SUGGESTION)
        try:
            response = await self.llm_service.generate(
                prompt,
                model=settings.OLLAMA_DEFAULT_MODEL,
                options={"temperature": 0.2, "num_predict": num_predict},
            )
            return self._parse_llm_json(response.get("response", ""))
        except OllamaRequestError:
            raise
        except LocalLLMError:
            raise

    async def _publish_progress(
        self,
        run: ContentOptimizationRun,
        progress: int,
        analysed: int,
        total: int,
        suggestions: int,
    ) -> None:
        """Write what has happened so far where the dashboard can see it.

        These counters used to be set once, by ``finish_run``, at the very end.
        Until then the run reported zero pages and zero suggestions however much
        work it had actually done, so an hour of generation looked identical to a
        hung process: a spinner, "Running", and nothing else. The operator had no
        way to tell progress from a stall — and on this stack a stall is a real
        possibility, which made the ambiguity worse.

        Publishing on every batch costs one small UPDATE and turns the stage into
        something you can watch: pages analysed out of pages selected, and
        suggestions found so far.
        """
        run.progress = min(95, progress)
        run.total_pages = analysed
        run.total_suggestions = suggestions
        await self.db.commit()
        logger.info(
            "Content optimization progress",
            run_id=str(run.id),
            analysed=analysed,
            selected=total,
            suggestions=suggestions,
            progress=run.progress,
        )

    def _pending_types(
        self,
        page,
        issue_types: set[str],
        internal_link_recs: List[Any],
        existing_keys: set[SuggestionKey],
    ) -> List[ContentOptimizationSuggestionType]:
        """The suggestion types this page does not already have an answer for.

        ``_suggestion_records`` discards any suggestion whose key is already
        stored, so a page whose every key exists produced nothing no matter what
        the model said. That work was still being paid for: a full generation per
        page, on every run. Because this agent runs on a schedule, most runs are
        repeat runs over pages nobody edited, which made it the common case
        rather than the exception.

        Computing the keys first costs a few hashes and decides whether the
        generation is worth starting at all.
        """
        pending: List[ContentOptimizationSuggestionType] = []
        for suggestion_type in self._target_types(page, issue_types, internal_link_recs):
            current_value = self._current_value(page, suggestion_type, internal_link_recs)
            content_hash = self._content_hash(page, suggestion_type, current_value, issue_types)
            if (page.id, suggestion_type, content_hash) not in existing_keys:
                pending.append(suggestion_type)
        return pending

    def _skip_reason(
        self,
        page,
        issue_types: set[str],
        internal_link_recs: List[Any],
        pending_types: List[ContentOptimizationSuggestionType],
    ) -> Optional[str]:
        """Why this page does not need a generation, or None if it does.

        One local model call costs tens of seconds of CPU, and the stage made one
        for every crawled page in sequence — a hundred-page site spent over an
        hour re-deriving advice for pages with nothing wrong with them.

        The tests applied here are the ones that change the answer:

        *Reachability.* A page Google will not index cannot be improved by better
        copy on it. A non-200 needs fixing, not rewriting, and the audit already
        reports that.

        *Material.* The prompt is built from the page's own text. Below a floor
        there is nothing for the model to summarise, and what comes back is
        invention rather than optimisation — which this product must not produce.

        *Deficiency.* A page with no audit issues, a title and description within
        length, exactly one h1, schema markup and no link recommendations has
        nothing identified to fix. Spending a minute asking anyway is how the
        stage came to take longer than the crawl that fed it.
        """
        if not pending_types:
            # Two different facts that would otherwise be logged as one. Now that
            # the requested types are need-driven, an empty list can mean the page
            # had nothing to ask about as easily as it can mean every answer is
            # already stored, and an operator reading the counts should be able to
            # tell "nothing to do here" from "done this already".
            if not self._target_types(page, issue_types, internal_link_recs):
                return "nothing_needed"
            return "already_suggested"

        status_code = getattr(page, "status_code", None)
        if status_code is not None and int(status_code) != 200:
            return "not_200"

        if getattr(page, "noindex", False):
            return "noindex"

        if int(page.word_count or 0) < LLM_MIN_WORD_COUNT:
            return "too_little_content"

        if issue_types or internal_link_recs:
            return None

        if self._has_weak_metadata(page):
            return None

        return "no_deficiency"

    def _has_weak_metadata(self, page) -> bool:
        """Whether the page's own fields show something worth rewriting.

        Deliberately the same bounds the suggestion validator already enforces,
        so this cannot select a page the rest of the service would then refuse to
        produce anything for.
        """
        title = (page.title or "").strip()
        if not title or len(title) < TITLE_MIN_LENGTH or len(title) > TITLE_MAX_LENGTH:
            return True
        if title.lower() in GENERIC_TITLES:
            return True

        meta = (page.meta_description or "").strip()
        if not meta or len(meta) < META_MIN_LENGTH or len(meta) > META_MAX_LENGTH:
            return True

        h1_source = page.h1 or []
        if isinstance(h1_source, str):
            h1_source = [h1_source]
        if len([value for value in h1_source if str(value).strip()]) != 1:
            return True

        if not getattr(page, "has_schema_markup", False):
            return True

        return False

    def _suggestion_records(
        self,
        run: ContentOptimizationRun,
        page,
        payload: Dict[str, Any],
        audit_issues: List[Any],
        page_score: Optional[Any],
        internal_link_recs: List[Any],
        existing_keys: set[SuggestionKey],
        target_types: Optional[List[ContentOptimizationSuggestionType]] = None,
    ) -> List[Dict[str, Any]]:
        issue_types = {issue.issue_type for issue in audit_issues}
        # Passed in by the caller, which already computed these to decide whether
        # the generation was worth running. Recomputing here would let the set
        # that justified the model call drift from the set it is applied to.
        if target_types is None:
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
        """The suggestion types this page has a reason to be asked about.

        Every page used to be asked for all seven base types plus whatever was
        conditional, so the model wrote a title for pages with a good title and
        schema for pages that already had schema. None of it was wasted output in
        the sense of being wrong — it was wasted because the page had no
        deficiency for it to address, and on a CPU-only Ollama the length of the
        reply *is* the runtime of the stage. A page needing one new description
        cost the same four minutes as a page needing everything.

        Each type below is now asked for only when something about the page says
        it is needed. The bounds are the ones the validator already enforces, so
        this cannot request something the rest of the service would then refuse
        to store, nor skip something it would have accepted.
        """
        values: List[ContentOptimizationSuggestionType] = []
        T = ContentOptimizationSuggestionType

        title = (page.title or "").strip()
        if (
            not title
            or len(title) < TITLE_MIN_LENGTH
            or len(title) > TITLE_MAX_LENGTH
            or title.lower() in GENERIC_TITLES
            or issue_types & {"missing_title", "title_too_short", "title_too_long", "duplicate_title"}
        ):
            values.append(T.seo_title)

        meta = (page.meta_description or "").strip()
        if (
            not meta
            or len(meta) < META_MIN_LENGTH
            or len(meta) > META_MAX_LENGTH
            or issue_types & {
                "missing_meta_description",
                "meta_description_too_short",
                "meta_description_too_long",
                "duplicate_meta_description",
            }
        ):
            values.append(T.meta_description)

        h1_source = page.h1 or []
        if isinstance(h1_source, str):
            h1_source = [h1_source]
        h1_values = [value for value in h1_source if str(value).strip()]
        if "missing_h1" in issue_types or "multiple_h1" in issue_types or len(h1_values) != 1:
            values.append(T.h1)

        # A long page with no subheadings is hard to scan and hard to extract an
        # answer from. A short one does not need them.
        h2_values = page.h2 or []
        if int(page.word_count or 0) >= AEO_MIN_WORD_COUNT and not h2_values:
            values.append(T.headings)

        if not getattr(page, "has_schema_markup", False) or "missing_schema" in issue_types:
            values.append(T.schema)

        if "thin_content" in issue_types or int(page.word_count or 0) < THIN_CONTENT_WORDS:
            values.append(T.content_refresh)

        # The two AEO additions. They are the reason an answer engine can quote
        # the page, so they are worth asking for — but only on a page with enough
        # substance to answer from, and not where the page already carries FAQ
        # markup of its own.
        if int(page.word_count or 0) >= AEO_MIN_WORD_COUNT:
            schema_types = {str(value).lower() for value in (getattr(page, "schema_types", None) or [])}
            if "faqpage" not in schema_types:
                values.append(T.faq)
            values.append(T.answer_block)

        if internal_link_recs:
            values.append(T.internal_link_context)

        return values

    def _build_prompt(
        self,
        page,
        audit_issues: List[Any],
        page_score: Optional[Any],
        internal_link_recs: List[Any],
        project_context_text: str = "",
        requested_types: Optional[List[ContentOptimizationSuggestionType]] = None,
    ) -> str:
        # Ask only for the sections that will actually be stored. Anything else
        # is output the model spends seconds producing and this service discards.
        wanted = {t.value for t in requested_types} if requested_types else set(SUGGESTION_JSON_SHAPES)
        shape_lines = ",\n".join(
            line for name, line in SUGGESTION_JSON_SHAPES.items() if name in wanted
        )
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
            "Return only valid JSON. Replace every <...> slot with your own text written for this "
            "specific page; never copy a slot back. Do not rewrite the whole page. Do not create "
            "spammy or keyword-stuffed text. "
            "Make concise page-level suggestions only; no visual/UI/UX changes and no publishing instructions.\n\n"
            f"{project_context_text}\n\n"
            "JSON shape:\n"
            "{\n"
            f"{shape_lines}\n"
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
        """Read the model's reply as an object, or say clearly that it was not one.

        A 3B model asked for JSON mostly returns JSON, and sometimes returns
        JSON wrapped in prose, or two objects, or one that stops mid-way because
        it hit the token budget. Every one of those used to escape this function
        as a raw ``JSONDecodeError``: the fallback ``json.loads`` below was
        unguarded, so the careful ``OllamaRequestError`` above it only covered
        the case where no braces were found at all. That bare decode error then
        travelled all the way up and failed the whole run.

        The attempts below are ordered cheapest first and all end the same way —
        an ``OllamaRequestError`` the caller can treat as "this page did not
        produce anything", which is a normal outcome, not a crash.
        """
        stripped = (text or "").strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
            stripped = re.sub(r"```$", "", stripped).strip()

        for candidate in self._json_candidates(stripped):
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data

        raise UnusableModelResponse("Model response did not contain a valid JSON object.")

    @staticmethod
    def _json_candidates(stripped: str) -> List[str]:
        """Progressively more forgiving readings of one reply.

        The last of these repairs a reply cut off by the token budget, by closing
        the structures still open at the last complete field. A page whose FAQ
        was truncated should still yield its title and description rather than
        nothing.
        """
        candidates = [stripped]

        # The outermost braces, for a reply wrapped in explanation.
        first, last = stripped.find("{"), stripped.rfind("}")
        if first != -1 and last > first:
            candidates.append(stripped[first:last + 1])

        # The first complete object, for a reply that ran two together.
        depth = 0
        for index, char in enumerate(stripped):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(stripped[stripped.find("{"):index + 1])
                    break

        # Truncated mid-object: keep everything up to the last field that closed,
        # then shut the structures the model left open.
        if first != -1:
            body = stripped[first:]
            cut = max(body.rfind("},"), body.rfind('",'), body.rfind("],"))
            if cut > 0:
                repaired = body[:cut + 1].rstrip(",")
                opens = repaired.count("{") - repaired.count("}")
                brackets = repaired.count("[") - repaired.count("]")
                candidates.append(repaired + "]" * max(brackets, 0) + "}" * max(opens, 0))

        return candidates

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

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        """Whether the model handed a prompt slot back instead of writing anything.

        Measured on six real pages, three replies were the slot text itself. A
        returned slot is the absence of an answer, and must not be dressed up as
        one.
        """
        stripped = value.strip()
        if stripped.startswith("<") and stripped.endswith(">"):
            return True
        lowered = stripped.lower()
        return any(
            marker in lowered
            for marker in ("your title here", "your description here", "char meta description",
                           "char title", "your answer", "your question", "<why>")
        )

    def _fit_or_drop(self, value: str, page, minimum: int, maximum: int) -> str:
        """Keep the model's own words, trimmed to fit — or return nothing.

        Three outcomes, and the middle one is the fix:

        *Too long* is salvageable. A description four characters over the limit
        is good copy that needs trimming, and trimming it keeps the model's
        meaning. The old code discarded it instead, because the length test sat
        in the reject branch and the truncation below it could then only ever
        apply to the replacement.

        *Too short, spammy, or a returned slot* means there is nothing to work
        with. This used to substitute a fixed sentence — "Explore {topic} with
        concise details, helpful context, and related resources for visitors" —
        and store it as a suggestion. Thirteen pages got near-identical copy that
        said nothing about them, presented as the agent's recommendation. An
        empty return drops the suggestion instead, which is honest: the page
        keeps its existing text, the gap stays visible in the audit, and the next
        run tries again.
        """
        candidate = self._clean_text(value)
        if not candidate or self._is_placeholder(candidate) or self._is_spammy(candidate):
            return ""
        if len(candidate) > maximum:
            candidate = self._truncate_words(candidate, maximum)
        if len(candidate) < minimum:
            return ""
        return candidate

    def _validate_title(self, value: str, page) -> str:
        return self._fit_or_drop(value, page, TITLE_MIN_LENGTH, TITLE_MAX_LENGTH)

    def _validate_meta(self, value: str, page) -> str:
        return self._fit_or_drop(value, page, META_MIN_LENGTH, META_MAX_LENGTH)

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
