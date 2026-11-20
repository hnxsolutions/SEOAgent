"""One-click SEO run orchestration service."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.models.audit import SEOAuditStatus
from app.models.content_optimization import ContentOptimizationRunStatus
from app.models.crawl import CrawlJob, CrawlPriority, CrawlStatus
from app.models.planner import SeoPlannerRunStatus, SeoPlannerRunType
from app.models.semantic import SemanticIndexStatus
from app.models.seo_run import SeoRun, SeoRunStage, SeoRunStageStatus, SeoRunStatus
from app.repositories.seo_run import SeoRunRepository
from app.services.audit import AuditService
from app.services.content_optimization import ContentOptimizationService
from app.services.crawl import CrawlService
from app.services.local_llm import LocalLLMError
from app.services.planner import PlannerService
from app.services.semantic import SemanticService

logger = structlog.get_logger(__name__)


#: How often a running SEO run proves it is still owned by a live process.
#: Short enough that a restart is noticed quickly, long enough that it is one
#: trivial UPDATE every half minute rather than a load of its own.
SEO_RUN_HEARTBEAT_SECONDS = 30


class SeoRunError(RuntimeError):
    """Raised when a required SEO run stage cannot complete."""


async def fail_stale_runs(
    db: AsyncSession,
    stale_after_seconds: Optional[int] = None,
    tenant_id: Optional[UUID] = None,
) -> int:
    """Close out runs whose owner is gone. Returns how many were closed.

    A run is executed by one process — an RQ worker, or the API's own background
    task when the queue is unavailable. If that process goes away mid-pipeline,
    nothing in the system notices: the row keeps saying ``running`` and the
    dashboard keeps showing a spinner, forever. A restart, a deploy, an OOM kill
    or a crash all produce this, so in production it is not an edge case — every
    deploy orphans whatever was in flight.

    The heartbeat above is what makes this safe to automate. Because a live run
    touches itself every ``SEO_RUN_HEARTBEAT_SECONDS``, silence for many
    multiples of that is not a slow stage; it is an absent process. Nothing is
    cancelled and no data is deleted — the work each stage finished is already
    committed and stays queryable. Only the run's own status is corrected, so
    the operator sees what actually happened and can start a new one.
    """
    threshold = stale_after_seconds or settings.SEO_RUN_STALE_AFTER_SECONDS
    cutoff = datetime.utcnow() - timedelta(seconds=threshold)

    query = select(SeoRun).where(
        SeoRun.status == SeoRunStatus.running,
        SeoRun.updated_at < cutoff,
    )
    if tenant_id is not None:
        query = query.where(SeoRun.tenant_id == tenant_id)

    stale = (await db.execute(query)).scalars().all()

    for run in stale:
        run.status = SeoRunStatus.failed
        run.error_message = (
            f"The process running this stopped responding for over "
            f"{threshold // 60} minutes and the run was closed. This normally "
            "means the worker was restarted mid-run. Results from the stages "
            "that finished are kept; start a new run to continue."
        )
        run.updated_at = datetime.utcnow()
        logger.warning(
            "seo_run_marked_stale",
            run_id=str(run.id),
            stage=run.current_stage.value if run.current_stage else None,
        )

    if stale:
        await db.commit()
    return len(stale)


class SeoRunService:
    """Coordinates the MVP SEO pipeline for one project."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        crawl_stall_timeout_seconds: Optional[int] = None,
        crawl_seconds_per_page: Optional[float] = None,
        crawl_min_timeout_seconds: Optional[int] = None,
        poll_interval_seconds: float = 2.0,
        crawl_service_factory=CrawlService,
        audit_service_factory=AuditService,
        semantic_service_factory=SemanticService,
        content_service_factory=ContentOptimizationService,
        planner_service_factory=PlannerService,
    ):
        self.db = db
        self.repository = SeoRunRepository(db)
        self.crawl_stall_timeout_seconds = (
            crawl_stall_timeout_seconds
            if crawl_stall_timeout_seconds is not None
            else settings.SEO_RUN_CRAWL_STALL_TIMEOUT_SECONDS
        )
        self.crawl_seconds_per_page = (
            crawl_seconds_per_page
            if crawl_seconds_per_page is not None
            else settings.SEO_RUN_CRAWL_SECONDS_PER_PAGE
        )
        self.crawl_min_timeout_seconds = (
            crawl_min_timeout_seconds
            if crawl_min_timeout_seconds is not None
            else settings.SEO_RUN_CRAWL_MIN_TIMEOUT_SECONDS
        )
        self.poll_interval_seconds = poll_interval_seconds
        self.crawl_service_factory = crawl_service_factory
        self.audit_service_factory = audit_service_factory
        self.semantic_service_factory = semantic_service_factory
        self.content_service_factory = content_service_factory
        self.planner_service_factory = planner_service_factory

    async def start_run(self, project_id: UUID, tenant_id: UUID) -> SeoRun:
        project = await self.repository.get_project(project_id, tenant_id)
        if not project:
            raise ValueError("Project not found")
        run = await self.repository.create_run(project, tenant_id)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def get_run_status(self, run_id: UUID, tenant_id: UUID) -> Optional[SeoRun]:
        await self._reap_before_reading(tenant_id)
        return await self.repository.get_run(run_id, tenant_id)

    async def list_runs(self, project_id: UUID, tenant_id: UUID, limit: int = 25, offset: int = 0) -> list[SeoRun]:
        await self._reap_before_reading(tenant_id)
        return await self.repository.list_runs(project_id, tenant_id, limit=limit, offset=offset)

    async def _reap_before_reading(self, tenant_id: UUID) -> None:
        """Correct abandoned runs at the moment someone asks about them.

        The scheduled reaper is not enough on its own, because it lives in the
        scheduler — and the scheduler is a process that can wedge, be stopped, or
        simply not be deployed. When that happened here, a run whose worker had
        been killed sat at "Running" on the dashboard for twelve hours: the row
        said one thing and reality said another, and nothing was ever going to
        reconcile them.

        Reading is the one moment the answer has to be right, so the check
        happens here too. It is a single indexed lookup over the handful of rows
        that claim to be running, and it never touches a run that is still
        beating.

        Failures are swallowed: showing a run that is slightly out of date is a
        far better outcome than failing the dashboard that was asked for it.
        """
        try:
            await fail_stale_runs(self.db, tenant_id=tenant_id)
        except Exception as exc:  # pragma: no cover - never break a read
            logger.warning("seo_run_lazy_reap_failed", error=str(exc))

    async def execute_run(
        self,
        run_id: UUID,
        tenant_id: UUID,
        *,
        max_pages: Optional[int] = None,
    ) -> SeoRun:
        """Run the pipeline.

        `max_pages` lets a deep monthly audit reach further than the weekly one
        without a second code path; omitted, it falls back to
        ``SEO_RUN_MAX_PAGES``.
        """
        run = await self.repository.get_run(run_id, tenant_id)
        if not run:
            # Name both ids. This failure was recorded 51 times as the bare words
            # "SEO run not found", with no run and no tenant attached, so there
            # was nothing to look up and nothing to act on. The usual cause is a
            # job outliving the tenant it was queued for — a deleted project or
            # test account — and that is only visible if the ids are in the
            # message.
            raise ValueError(
                f"SEO run {run_id} was not found for tenant {tenant_id}. "
                "The run or its tenant was most likely deleted after this job "
                "was queued."
            )

        await self.repository.set_status(run, SeoRunStatus.running, current_stage=SeoRunStage.crawl)
        await self.db.commit()

        # Proof of life for as long as this run owns the pipeline. Without it a
        # run is only touched when a stage changes, and a stage can legitimately
        # work for an hour — so there is no way to tell a long content pass from
        # a process that died halfway through one. When this task stops, the
        # process is gone, and `fail_stale_runs` can say so instead of leaving
        # "Running" on the dashboard forever.
        heartbeat = asyncio.create_task(self._heartbeat(run_id))

        current_stage = SeoRunStage.crawl
        try:
            project = await self.repository.get_project(run.project_id, tenant_id)
            if not project:
                raise ValueError("Project not found")

            # Each stage is skipped when this run already finished it. A run
            # that died in content used to be restarted from the crawl, paying
            # again for an eight-minute crawl, an audit and twenty minutes of
            # embedding that were all still sitting in the database, finished and
            # correct. Resuming reuses them and goes straight back to the stage
            # that stopped.
            crawl = await self._resume_or_run(
                run, SeoRunStage.crawl,
                lambda: self._run_crawl(run, project.domain, tenant_id, max_pages=max_pages),
                lambda: self._load_crawl(run, tenant_id),
            )
            current_stage = SeoRunStage.audit
            audit = await self._resume_or_run(
                run, SeoRunStage.audit,
                lambda: self._run_audit(run, crawl.id, tenant_id),
                lambda: self._load_audit(run, tenant_id),
            )
            current_stage = SeoRunStage.semantic_index
            semantic = await self._resume_or_run(
                run, SeoRunStage.semantic_index,
                lambda: self._run_semantic(run, crawl.id, tenant_id),
                lambda: self._load_semantic(run, tenant_id),
            )
            current_stage = SeoRunStage.content_optimization
            content = await self._resume_or_run(
                run, SeoRunStage.content_optimization,
                lambda: self._run_content(run, crawl.id, tenant_id),
                lambda: self._load_content(run),
            )
            current_stage = SeoRunStage.planner
            planner = await self._run_planner(run, tenant_id)

            await self.repository.attach_ids(
                run,
                crawl_id=crawl.id,
                audit_id=audit.id,
                semantic_index_run_id=semantic.id,
                content_optimization_run_id=getattr(content, "id", None),
                planner_run_id=planner.id,
            )
            await self.repository.set_status(run, SeoRunStatus.completed, current_stage=SeoRunStage.completed)
            await self.db.commit()
            await self.db.refresh(run)
            logger.info("Completed one-click SEO run", run_id=str(run.id), project_id=str(run.project_id))
            return run
        except Exception as exc:
            return await self._fail_run(run_id, tenant_id, current_stage, exc)
        finally:
            heartbeat.cancel()

    #: Pipeline order. Resuming from a stage means everything at or after it is
    #: redone, because a later stage's result was computed from the earlier one
    #: and keeping it would mix old conclusions with new data.
    STAGE_ORDER = (
        SeoRunStage.crawl,
        SeoRunStage.audit,
        SeoRunStage.semantic_index,
        SeoRunStage.content_optimization,
        SeoRunStage.planner,
    )

    async def reset_from_stage(self, run: SeoRun, stage: SeoRunStage) -> SeoRun:
        """Mark `stage` and everything after it as not done, so a resume redoes them.

        Stages before it keep their completed status and their stored artefacts,
        which is the whole point: re-running the planner should not mean paying
        for the crawl, the audit and twenty minutes of embeddings again.
        """
        if run.status == SeoRunStatus.running:
            # Resetting a run that is still executing corrupts it from both ends:
            # the worker keeps going against stage statuses that have been moved
            # underneath it, and a second worker starts the same stage. That is
            # exactly what happened — a content stage already past 38 pages had its
            # status pushed back to "pending", so the dashboard showed "Queued"
            # beside a progress bar that was plainly moving.
            raise ValueError(
                "This run is still going. Wait for it to finish or fail before "
                "re-running a stage."
            )

        try:
            first = self.STAGE_ORDER.index(stage)
        except ValueError:
            raise ValueError(f"{stage} is not a stage that can be resumed from")

        statuses = dict(run.stage_statuses or {})
        errors = dict(getattr(run, "stage_errors", None) or {})
        for later in self.STAGE_ORDER[first:]:
            statuses[later.value] = SeoRunStageStatus.pending.value
            errors.pop(later.value, None)

        run.stage_statuses = statuses
        if hasattr(run, "stage_errors"):
            run.stage_errors = errors
        run.current_stage = stage
        run.error_message = None
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("Run reset for resume", run_id=str(run.id), from_stage=stage.value)
        return run

    async def _resume_or_run(self, run, stage, work, load):
        """Reuse this run's finished stage, or do it.

        A stage counts as done only when its status says completed *and* the
        artefact it produced is still loadable — a status with nothing behind it
        is a bookkeeping error, not a result, and re-running is the safe reading.
        """
        if self._stage_status(run, stage) == SeoRunStageStatus.completed.value:
            existing = await load()
            if existing is not None:
                logger.info("Reusing completed stage", run_id=str(run.id), stage=stage.value)
                return existing
            logger.warning(
                "Stage marked complete but its result is gone; re-running",
                run_id=str(run.id),
                stage=stage.value,
            )
        return await work()

    @staticmethod
    def _stage_status(run: SeoRun, stage: SeoRunStage) -> Optional[str]:
        return (run.stage_statuses or {}).get(stage.value)

    async def _load_crawl(self, run: SeoRun, tenant_id: UUID):
        if not run.crawl_id:
            return None
        return await self.crawl_service_factory(self.db).get_crawl_job(run.crawl_id, tenant_id)

    async def _load_audit(self, run: SeoRun, tenant_id: UUID):
        if not run.audit_id:
            return None
        return await self.audit_service_factory(self.db).get_audit_status(run.audit_id, tenant_id)

    async def _load_content(self, run: SeoRun):
        if not run.content_optimization_run_id:
            return None
        return await self.content_service_factory(self.db).get_run_status(
            run.content_optimization_run_id, run.tenant_id
        )

    async def _load_semantic(self, run: SeoRun, tenant_id: UUID):
        if not run.semantic_index_run_id:
            return None
        return await self.semantic_service_factory(self.db).get_index_status(
            run.semantic_index_run_id, tenant_id
        )

    async def _run_crawl(
        self,
        run: SeoRun,
        project_domain: str,
        tenant_id: UUID,
        *,
        max_pages: Optional[int] = None,
    ):
        """Crawl the site.

        The page budget was hardcoded at 5 — a demo setting that shipped as the
        production default, so every audit, every planner task and every content
        gap on a real site was computed from five pages. It is now configurable
        and defaults to ``SEO_RUN_MAX_PAGES``.

        `respect_robots_txt` is on. It was off, which is indefensible for an
        agent that crawls other people's sites on a schedule — and a crawler
        that ignores robots.txt will eventually get the product blocked.
        """
        budget = int(max_pages or settings.SEO_RUN_MAX_PAGES)
        budget = max(1, min(budget, 10000))

        await self._set_stage(run, SeoRunStage.crawl, SeoRunStageStatus.running)
        crawl_service = self.crawl_service_factory(self.db)
        crawl = await crawl_service.create_crawl_job(
            url=self._project_url(project_domain),
            tenant_id=tenant_id,
            project_id=run.project_id,
            name=f"SEO run {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            priority=CrawlPriority.normal,
            max_pages=budget,
            # Deep enough to reach a service or blog page from the homepage;
            # depth 1 only ever saw the homepage's direct links.
            depth=3,
            render_javascript=False,
            respect_robots_txt=True,
        )
        await self.repository.attach_ids(run, crawl_id=crawl.id)
        await self.db.commit()

        crawl = await crawl_service.enqueue_crawl_job(crawl.id, tenant_id=tenant_id)
        await self.repository.attach_ids(run, crawl_id=crawl.id)
        await self.db.commit()

        crawl, partial_note = await self._wait_for_crawl(crawl_service, crawl.id, tenant_id)

        if partial_note is None and crawl.status != CrawlStatus.completed:
            raise SeoRunError(f"Crawl ended with status {self._enum_value(crawl.status)}: {crawl.error_message or ''}".strip())

        # A crawl that ran out of budget with pages in hand is reported as
        # completed-with-a-note, not failed: the downstream stages can audit
        # what was collected, and a run that produces a partial audit is worth
        # more to the operator than one that produces nothing.
        await self._set_stage(
            run,
            SeoRunStage.crawl,
            SeoRunStageStatus.completed,
            error_message=partial_note,
        )
        return crawl

    async def _run_audit(self, run: SeoRun, crawl_id: UUID, tenant_id: UUID):
        await self._set_stage(run, SeoRunStage.audit, SeoRunStageStatus.running)
        audit_service = self.audit_service_factory(self.db)
        audit = await audit_service.start_audit(crawl_id, tenant_id)
        await self.repository.attach_ids(run, audit_id=audit.id)
        await self.db.commit()
        audit = await audit_service.execute_audit(audit.id)
        if audit.status != SEOAuditStatus.completed:
            raise SeoRunError(f"Audit ended with status {self._enum_value(audit.status)}: {audit.error_message or ''}".strip())
        await self._set_stage(run, SeoRunStage.audit, SeoRunStageStatus.completed)
        return audit

    async def _run_semantic(self, run: SeoRun, crawl_id: UUID, tenant_id: UUID):
        await self._set_stage(run, SeoRunStage.semantic_index, SeoRunStageStatus.running)
        semantic_service = self.semantic_service_factory(self.db)
        semantic = await semantic_service.start_index(crawl_id, tenant_id)
        await self.repository.attach_ids(run, semantic_index_run_id=semantic.id)
        await self.db.commit()
        semantic = await semantic_service.execute_index(semantic.id)
        if semantic.status != SemanticIndexStatus.completed:
            raise SeoRunError(f"Semantic index ended with status {self._enum_value(semantic.status)}: {semantic.error_message or ''}".strip())
        await self._set_stage(run, SeoRunStage.semantic_index, SeoRunStageStatus.completed)
        return semantic

    async def _run_content(self, run: SeoRun, crawl_id: UUID, tenant_id: UUID):
        await self._set_stage(run, SeoRunStage.content_optimization, SeoRunStageStatus.running)
        content_service = self.content_service_factory(self.db)
        content = await content_service.start_generation(crawl_id, tenant_id)
        await self.repository.attach_ids(run, content_optimization_run_id=content.id)
        await self.db.commit()
        try:
            content = await content_service.execute_generation(content.id)
            if content.status == ContentOptimizationRunStatus.completed:
                await self._set_stage(run, SeoRunStage.content_optimization, SeoRunStageStatus.completed)
            else:
                await self._set_stage(
                    run,
                    SeoRunStage.content_optimization,
                    SeoRunStageStatus.skipped_or_failed,
                    error_message=content.error_message or "Content optimization did not complete.",
                )
            return content
        except LocalLLMError as exc:
            await self._set_stage(
                run,
                SeoRunStage.content_optimization,
                SeoRunStageStatus.skipped_or_failed,
                error_message=str(exc),
            )
            logger.warning("Content optimization skipped during SEO run", run_id=str(run.id), error=str(exc))
            return content

    async def _run_planner(self, run: SeoRun, tenant_id: UUID):
        await self._set_stage(run, SeoRunStage.planner, SeoRunStageStatus.running)
        planner_service = self.planner_service_factory(self.db)
        planner = await planner_service.run_project(run.project_id, tenant_id, run_type=SeoPlannerRunType.manual)
        if planner.status != SeoPlannerRunStatus.completed:
            raise SeoRunError(f"Planner ended with status {self._enum_value(planner.status)}: {planner.error_message or ''}".strip())
        await self.repository.attach_ids(run, planner_run_id=planner.id)
        await self._set_stage(run, SeoRunStage.planner, SeoRunStageStatus.completed)
        return planner

    async def _heartbeat(self, run_id: UUID) -> None:
        """Touch the run every interval for as long as this process owns it.

        Uses its own session on purpose. ``self.db`` is a single connection the
        pipeline is already using, and driving it from a concurrent task
        corrupts its state; a short-lived session per beat costs one UPDATE and
        shares nothing.

        Errors are swallowed. A heartbeat that fails is a monitoring problem,
        and it must never be the reason a real SEO run dies.
        """
        from app.core.database import async_session_maker

        while True:
            try:
                await asyncio.sleep(SEO_RUN_HEARTBEAT_SECONDS)
                async with async_session_maker() as session:
                    await session.execute(
                        update(SeoRun)
                        .where(SeoRun.id == run_id, SeoRun.status == SeoRunStatus.running)
                        .values(updated_at=datetime.utcnow())
                    )
                    await session.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - monitoring must not break the run
                logger.debug("seo_run_heartbeat_failed", run_id=str(run_id), error=str(exc))

    def _crawl_ceiling_seconds(self, max_pages: Optional[int]) -> float:
        """The absolute backstop for one crawl, scaled to the work requested.

        A constant here is the thing that broke: the same number cannot serve a
        5-page site and a 5,000-page one. Scaling by the page budget keeps the
        ceiling a backstop rather than the thing that decides the outcome.
        """
        pages = max(1, int(max_pages or 1))
        return max(float(self.crawl_min_timeout_seconds), pages * self.crawl_seconds_per_page)

    async def _wait_for_crawl(
        self,
        crawl_service: CrawlService,
        crawl_id: UUID,
        tenant_id: UUID,
    ) -> tuple[CrawlJob, Optional[str]]:
        """Wait for the crawl, watching progress rather than the clock.

        Returns the job and, when the crawl was cut short with pages already
        saved, a note describing why — the caller decides whether that partial
        result is worth continuing with.

        **Why progress and not elapsed time.** A fixed wall-clock budget cannot
        be right for a work item whose size is a parameter. Six hundred seconds
        was ten times more than a five-page site needs and not enough for a
        healthy 99-page crawl of a real site, which this cut off at page 78 —
        and every page already fetched was thrown away with it. A thousand-page
        site would not have survived its first tenth.

        So the question asked here is "is this crawl still making progress?".
        A crawl that keeps saving pages keeps its budget, however long it runs.
        Only one that has gone quiet for ``crawl_stall_timeout_seconds`` is
        abandoned — which is the condition that actually means something is
        wrong: a hung worker, a dead queue, a site that stopped answering.

        The ceiling above it exists for the pathological case, a site slow
        enough to deliver one page just inside every stall window, and scales
        with the page budget so it never becomes the limit in normal use.
        """
        loop = asyncio.get_running_loop()
        terminal = {CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled}

        stall_deadline = loop.time() + self.crawl_stall_timeout_seconds
        # Set on the first poll, once the job tells us how many pages it is for.
        ceiling: Optional[float] = None
        last_progress = -1

        while True:
            self.db.expire_all()
            crawl = await crawl_service.get_crawl_job(crawl_id, tenant_id)
            if crawl is None:
                raise SeoRunError("Crawl job could not be read while waiting for it.")
            if crawl.status in terminal:
                return crawl, None

            if ceiling is None:
                ceiling = loop.time() + self._crawl_ceiling_seconds(crawl.max_pages)

            # Failed pages count as progress: a crawl working through a run of
            # 404s is busy, not stuck.
            progress = (crawl.total_pages_crawled or 0) + (crawl.total_pages_failed or 0)
            if progress > last_progress:
                last_progress = progress
                stall_deadline = loop.time() + self.crawl_stall_timeout_seconds

            now = loop.time()
            if now >= stall_deadline:
                return await self._abandon_crawl(
                    crawl_service,
                    crawl,
                    tenant_id,
                    f"stopped making progress for {self.crawl_stall_timeout_seconds}s",
                    progress,
                )
            if now >= ceiling:
                return await self._abandon_crawl(
                    crawl_service,
                    crawl,
                    tenant_id,
                    f"reached its time ceiling for {crawl.max_pages} pages",
                    progress,
                )

            await asyncio.sleep(self.poll_interval_seconds)

    async def _abandon_crawl(
        self,
        crawl_service: CrawlService,
        crawl: CrawlJob,
        tenant_id: UUID,
        reason: str,
        pages: int,
    ) -> tuple[CrawlJob, Optional[str]]:
        """Stop a crawl that will not finish, keeping whatever it did collect.

        Cancelling tells the worker to stop spending time on a job nobody is
        waiting for any more. The pages already written stay written: an audit
        of 78 real pages is worth incomparably more than a failed run, which is
        what the old code produced from exactly the same data.
        """
        logger.warning(
            "Crawl abandoned before completion",
            crawl_id=str(crawl.id),
            reason=reason,
            pages_collected=pages,
        )
        try:
            cancelled = await crawl_service.cancel_crawl(crawl.id, tenant_id)
            if cancelled is not None:
                crawl = cancelled
        except Exception as exc:  # pragma: no cover - cancellation is best effort
            logger.warning("Could not cancel abandoned crawl", crawl_id=str(crawl.id), error=str(exc))

        if pages <= 0:
            # Nothing to audit. This is the one case that is still a failure.
            raise SeoRunError(f"Crawl {reason} without collecting any pages.")

        return crawl, f"Crawl {reason}; continuing with the {pages} pages already collected."

    async def _set_stage(
        self,
        run: SeoRun,
        stage: SeoRunStage,
        status: SeoRunStageStatus,
        error_message: Optional[str] = None,
    ) -> None:
        await self.repository.set_stage(run, stage, status, error_message=error_message)
        await self.db.commit()
        from app.services.stage_telemetry import record_stage

        await record_stage(self.db, run, stage, status, error_message=error_message)

    async def _fail_run(self, run_id: UUID, tenant_id: UUID, stage: SeoRunStage, exc: Exception) -> SeoRun:
        await self.db.rollback()
        run = await self.repository.get_run(run_id, tenant_id)
        if not run:
            raise exc
        error_message = str(exc)
        await self.repository.set_stage(run, stage, SeoRunStageStatus.failed, error_message=error_message)
        await self.repository.set_status(run, SeoRunStatus.failed, current_stage=stage, error_message=error_message)
        await self.db.commit()
        from app.services.stage_telemetry import record_stage

        await record_stage(self.db, run, stage, SeoRunStageStatus.failed, error_message=error_message)
        await self.db.refresh(run)
        logger.error("One-click SEO run failed", run_id=str(run.id), stage=stage.value, error=error_message, exc_info=True)
        return run

    def _project_url(self, domain: str) -> str:
        value = (domain or "").strip()
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith(("localhost", "127.", "frontend")) or ":" in value:
            return f"http://{value}"
        return f"https://{value}"

    def _enum_value(self, value) -> str:
        return getattr(value, "value", value)
