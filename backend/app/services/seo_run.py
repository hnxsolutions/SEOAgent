"""One-click SEO run orchestration service."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.audit import SEOAuditStatus
from app.models.content_optimization import ContentOptimizationRunStatus
from app.models.crawl import CrawlPriority, CrawlStatus
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


class SeoRunError(RuntimeError):
    """Raised when a required SEO run stage cannot complete."""


class SeoRunService:
    """Coordinates the MVP SEO pipeline for one project."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        crawl_timeout_seconds: int = 600,
        poll_interval_seconds: float = 2.0,
        crawl_service_factory=CrawlService,
        audit_service_factory=AuditService,
        semantic_service_factory=SemanticService,
        content_service_factory=ContentOptimizationService,
        planner_service_factory=PlannerService,
    ):
        self.db = db
        self.repository = SeoRunRepository(db)
        self.crawl_timeout_seconds = crawl_timeout_seconds
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
        return await self.repository.get_run(run_id, tenant_id)

    async def list_runs(self, project_id: UUID, tenant_id: UUID, limit: int = 25, offset: int = 0) -> list[SeoRun]:
        return await self.repository.list_runs(project_id, tenant_id, limit=limit, offset=offset)

    async def execute_run(self, run_id: UUID, tenant_id: UUID) -> SeoRun:
        run = await self.repository.get_run(run_id, tenant_id)
        if not run:
            raise ValueError("SEO run not found")

        await self.repository.set_status(run, SeoRunStatus.running, current_stage=SeoRunStage.crawl)
        await self.db.commit()

        current_stage = SeoRunStage.crawl
        try:
            project = await self.repository.get_project(run.project_id, tenant_id)
            if not project:
                raise ValueError("Project not found")

            crawl = await self._run_crawl(run, project.domain, tenant_id)
            current_stage = SeoRunStage.audit
            audit = await self._run_audit(run, crawl.id, tenant_id)
            current_stage = SeoRunStage.semantic_index
            semantic = await self._run_semantic(run, crawl.id, tenant_id)
            current_stage = SeoRunStage.content_optimization
            content = await self._run_content(run, crawl.id, tenant_id)
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

    async def _run_crawl(self, run: SeoRun, project_domain: str, tenant_id: UUID):
        await self._set_stage(run, SeoRunStage.crawl, SeoRunStageStatus.running)
        crawl_service = self.crawl_service_factory(self.db)
        crawl = await crawl_service.create_crawl_job(
            url=self._project_url(project_domain),
            tenant_id=tenant_id,
            project_id=run.project_id,
            name=f"SEO run {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            priority=CrawlPriority.normal,
            max_pages=5,
            depth=1,
            render_javascript=False,
            respect_robots_txt=False,
        )
        await self.repository.attach_ids(run, crawl_id=crawl.id)
        await self.db.commit()

        crawl = await crawl_service.enqueue_crawl_job(crawl.id, tenant_id=tenant_id)
        await self.repository.attach_ids(run, crawl_id=crawl.id)
        await self.db.commit()

        crawl = await self._wait_for_crawl(crawl_service, crawl.id, tenant_id)
        if crawl.status != CrawlStatus.completed:
            raise SeoRunError(f"Crawl ended with status {self._enum_value(crawl.status)}: {crawl.error_message or ''}".strip())
        await self._set_stage(run, SeoRunStage.crawl, SeoRunStageStatus.completed)
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

    async def _wait_for_crawl(self, crawl_service: CrawlService, crawl_id: UUID, tenant_id: UUID):
        deadline = asyncio.get_running_loop().time() + self.crawl_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            self.db.expire_all()
            crawl = await crawl_service.get_crawl_job(crawl_id, tenant_id)
            if crawl and crawl.status in {CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled}:
                return crawl
            await asyncio.sleep(self.poll_interval_seconds)
        raise SeoRunError("Crawl timed out before completion.")

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
