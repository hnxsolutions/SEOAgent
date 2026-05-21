"""Repository layer for safe blog publishing and infrastructure checks."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog import BlogDraft
from app.models.blog_publishing import (
    BlogInfrastructureCheck,
    BlogPublishConnection,
    BlogPublishConnectionStatus,
    BlogPublishMode,
    BlogPublishProvider,
    BlogPublishResult,
    BlogPublishRun,
    BlogPublishRunStatus,
)
from app.models.project import Project
from app.models.repo_agent import RepoConnection


class BlogPublishingRepository:
    """Database access for blog publishing workflows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_connection(self, values: dict) -> BlogPublishConnection:
        connection = BlogPublishConnection(**values)
        self.db.add(connection)
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def list_connections(
        self,
        tenant_id: UUID,
        project_id: UUID,
        provider: Optional[BlogPublishProvider] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[BlogPublishConnection]:
        query = select(BlogPublishConnection).where(
            BlogPublishConnection.tenant_id == tenant_id,
            BlogPublishConnection.project_id == project_id,
        )
        if provider:
            query = query.where(BlogPublishConnection.provider == provider)
        query = query.order_by(BlogPublishConnection.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_connection(
        self,
        connection_id: UUID,
        tenant_id: UUID,
    ) -> Optional[BlogPublishConnection]:
        result = await self.db.execute(
            select(BlogPublishConnection).where(
                BlogPublishConnection.id == connection_id,
                BlogPublishConnection.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_connection_status(
        self,
        connection: BlogPublishConnection,
        status: BlogPublishConnectionStatus,
    ) -> BlogPublishConnection:
        connection.status = status
        connection.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def get_repo_connection(
        self,
        repo_connection_id: UUID,
        tenant_id: UUID,
    ) -> Optional[RepoConnection]:
        result = await self.db.execute(
            select(RepoConnection).where(
                RepoConnection.id == repo_connection_id,
                RepoConnection.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def latest_repo_connection(
        self,
        project_id: UUID,
        tenant_id: UUID,
    ) -> Optional[RepoConnection]:
        result = await self.db.execute(
            select(RepoConnection)
            .where(RepoConnection.project_id == project_id, RepoConnection.tenant_id == tenant_id)
            .order_by(RepoConnection.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_draft(self, draft_id: UUID, tenant_id: UUID) -> Optional[BlogDraft]:
        result = await self.db.execute(
            select(BlogDraft).where(BlogDraft.id == draft_id, BlogDraft.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create_infrastructure_check(self, values: dict) -> BlogInfrastructureCheck:
        check = BlogInfrastructureCheck(**values)
        self.db.add(check)
        await self.db.flush()
        await self.db.refresh(check)
        return check

    async def latest_infrastructure_check(
        self,
        project_id: UUID,
        tenant_id: UUID,
    ) -> Optional[BlogInfrastructureCheck]:
        result = await self.db.execute(
            select(BlogInfrastructureCheck)
            .where(
                BlogInfrastructureCheck.project_id == project_id,
                BlogInfrastructureCheck.tenant_id == tenant_id,
            )
            .order_by(BlogInfrastructureCheck.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_run(
        self,
        *,
        tenant_id: UUID,
        project_id: Optional[UUID],
        blog_draft_id: Optional[UUID],
        connection_id: Optional[UUID],
        provider: BlogPublishProvider,
        mode: BlogPublishMode,
    ) -> BlogPublishRun:
        run = BlogPublishRun(
            tenant_id=tenant_id,
            project_id=project_id,
            blog_draft_id=blog_draft_id,
            connection_id=connection_id,
            provider=provider,
            mode=mode,
            status=BlogPublishRunStatus.queued,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def set_run_status(
        self,
        run: BlogPublishRun,
        status: BlogPublishRunStatus,
        error_message: Optional[str] = None,
    ) -> BlogPublishRun:
        now = datetime.utcnow()
        run.status = status
        run.error_message = error_message
        if status == BlogPublishRunStatus.running and not run.started_at:
            run.started_at = now
        if status in {
            BlogPublishRunStatus.completed,
            BlogPublishRunStatus.failed,
            BlogPublishRunStatus.rolled_back,
        }:
            run.completed_at = now
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: UUID, tenant_id: UUID) -> Optional[BlogPublishRun]:
        result = await self.db.execute(
            select(BlogPublishRun).where(BlogPublishRun.id == run_id, BlogPublishRun.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def add_results(self, records: Iterable[dict]) -> List[BlogPublishResult]:
        results = []
        for values in records:
            result = BlogPublishResult(**values)
            self.db.add(result)
            results.append(result)
        await self.db.flush()
        for result in results:
            await self.db.refresh(result)
        return results

    async def get_result_for_run(
        self,
        run_id: UUID,
        tenant_id: UUID,
    ) -> Optional[BlogPublishResult]:
        result = await self.db.execute(
            select(BlogPublishResult)
            .where(BlogPublishResult.publish_run_id == run_id, BlogPublishResult.tenant_id == tenant_id)
            .order_by(BlogPublishResult.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
