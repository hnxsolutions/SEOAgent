"""Repository layer for Search Console imports, syncs, and opportunities."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SEOIssue, SEOIssueStatus, SEOPageScore
from app.models.blog import BlogTopic
from app.models.content_optimization import ContentOptimizationSuggestion
from app.models.crawl import CrawlJob, CrawlPage
from app.models.geo_aeo import GeoAeoPageScore
from app.models.internal_linking import InternalLinkRecommendation
from app.models.project import Project
from app.models.tenant import tenant_members
from app.models.user import User
from app.models.search_console import (
    GSCComparisonWindow,
    GSCConnection,
    GSCConnectionStatus,
    GSCProperty,
    GSCPropertySourceType,
    GSCPropertyType,
    GSCSyncJob,
    GSCSyncJobStatus,
    GSCSyncType,
    SearchConsoleImport,
    SearchConsoleImportStatus,
    SearchConsoleOpportunity,
    SearchConsoleOpportunityStatus,
    SearchConsoleOpportunityType,
    SearchConsolePeriod,
    SearchConsoleRow,
    SearchConsoleSourceType,
)


class SearchConsoleRepository:
    """Persistence and signal access for Search Console intelligence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_user_in_tenant(self, user_id: UUID, tenant_id: UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User)
            .join(tenant_members, tenant_members.c.user_id == User.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                tenant_members.c.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_connection(
        self,
        tenant_id: UUID,
        user_id: UUID,
        encrypted_refresh_token: str,
        access_token_expires_at: Optional[datetime],
        scopes: list[str],
        metadata: Optional[dict] = None,
    ) -> GSCConnection:
        existing = await self.latest_connection(tenant_id, user_id=user_id, include_failed=True)
        if existing:
            existing.encrypted_refresh_token = encrypted_refresh_token
            existing.access_token_expires_at = access_token_expires_at
            existing.scopes = scopes
            existing.status = GSCConnectionStatus.connected
            existing.metadata_json = metadata or {}
            existing.updated_at = datetime.utcnow()
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        connection = GSCConnection(
            tenant_id=tenant_id,
            user_id=user_id,
            provider="google",
            encrypted_refresh_token=encrypted_refresh_token,
            access_token_expires_at=access_token_expires_at,
            scopes=scopes,
            status=GSCConnectionStatus.connected,
            metadata_json=metadata or {},
        )
        self.db.add(connection)
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def latest_connection(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        include_failed: bool = False,
    ) -> Optional[GSCConnection]:
        query = select(GSCConnection).where(GSCConnection.tenant_id == tenant_id, GSCConnection.provider == "google")
        if user_id:
            query = query.where(GSCConnection.user_id == user_id)
        if not include_failed:
            query = query.where(GSCConnection.status == GSCConnectionStatus.connected)
        query = query.order_by(GSCConnection.updated_at.desc(), GSCConnection.created_at.desc()).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_connection(
        self,
        connection_id: UUID,
        tenant_id: UUID,
        include_failed: bool = False,
    ) -> Optional[GSCConnection]:
        query = select(GSCConnection).where(
            GSCConnection.id == connection_id,
            GSCConnection.tenant_id == tenant_id,
            GSCConnection.provider == "google",
        )
        if not include_failed:
            query = query.where(GSCConnection.status == GSCConnectionStatus.connected)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def set_connection_status(
        self,
        connection: GSCConnection,
        status: GSCConnectionStatus,
    ) -> GSCConnection:
        connection.status = status
        connection.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def upsert_properties(
        self,
        connection: GSCConnection,
        properties: Iterable[dict],
    ) -> List[GSCProperty]:
        upserted: List[GSCProperty] = []
        for item in properties:
            site_url = item.get("site_url") or item.get("siteUrl")
            if not site_url:
                continue
            result = await self.db.execute(
                select(GSCProperty).where(
                    GSCProperty.tenant_id == connection.tenant_id,
                    GSCProperty.connection_id == connection.id,
                    GSCProperty.site_url == site_url,
                )
            )
            prop = result.scalar_one_or_none()
            if prop:
                prop.permission_level = item.get("permission_level") or item.get("permissionLevel")
                prop.source_type = GSCPropertySourceType.oauth
                prop.property_type = infer_gsc_property_type(site_url)
                prop.updated_at = datetime.utcnow()
            else:
                prop = GSCProperty(
                    tenant_id=connection.tenant_id,
                    connection_id=connection.id,
                    site_url=site_url,
                    source_type=GSCPropertySourceType.oauth,
                    property_type=infer_gsc_property_type(site_url),
                    permission_level=item.get("permission_level") or item.get("permissionLevel"),
                    is_selected=False,
                )
                self.db.add(prop)
            await self.db.flush()
            await self.db.refresh(prop)
            upserted.append(prop)
        return upserted

    async def upsert_manual_property(
        self,
        tenant_id: UUID,
        project_id: UUID,
        site_url: str,
        property_type: GSCPropertyType,
        notes: Optional[str] = None,
    ) -> GSCProperty:
        result = await self.db.execute(
            select(GSCProperty).where(
                GSCProperty.tenant_id == tenant_id,
                GSCProperty.project_id == project_id,
                GSCProperty.source_type == GSCPropertySourceType.manual,
                GSCProperty.site_url == site_url,
            )
        )
        prop = result.scalar_one_or_none()
        selected = await self.selected_property(project_id, tenant_id)
        should_select = selected is None
        if prop:
            prop.property_type = property_type
            prop.notes = notes
            prop.permission_level = None
            if should_select:
                prop.is_selected = True
            prop.updated_at = datetime.utcnow()
        else:
            prop = GSCProperty(
                tenant_id=tenant_id,
                project_id=project_id,
                connection_id=None,
                site_url=site_url,
                source_type=GSCPropertySourceType.manual,
                property_type=property_type,
                permission_level=None,
                notes=notes,
                is_selected=should_select,
            )
            self.db.add(prop)
        await self.db.flush()
        await self.db.refresh(prop)
        return prop

    async def list_properties(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
    ) -> List[GSCProperty]:
        query = select(GSCProperty).where(GSCProperty.tenant_id == tenant_id)
        if project_id:
            query = query.where(or_(GSCProperty.project_id == project_id, GSCProperty.project_id.is_(None)))
        query = query.order_by(GSCProperty.is_selected.desc(), GSCProperty.site_url.asc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_property(self, property_id: UUID, tenant_id: UUID) -> Optional[GSCProperty]:
        result = await self.db.execute(
            select(GSCProperty).where(GSCProperty.id == property_id, GSCProperty.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def select_property(
        self,
        project_id: UUID,
        tenant_id: UUID,
        property_id: UUID,
    ) -> GSCProperty:
        prop = await self.get_property(property_id, tenant_id)
        if not prop:
            raise ValueError("GSC property not found")
        if prop.project_id and prop.project_id != project_id:
            raise ValueError("GSC property belongs to a different project")
        await self.db.execute(
            select(GSCProperty).where(GSCProperty.tenant_id == tenant_id, GSCProperty.project_id == project_id)
        )
        existing = await self.list_properties(tenant_id, project_id=project_id)
        for item in existing:
            if item.project_id == project_id:
                item.is_selected = False
        prop.project_id = project_id
        prop.is_selected = True
        prop.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(prop)
        return prop

    async def selected_property(self, project_id: UUID, tenant_id: UUID) -> Optional[GSCProperty]:
        result = await self.db.execute(
            select(GSCProperty).where(
                GSCProperty.tenant_id == tenant_id,
                GSCProperty.project_id == project_id,
                GSCProperty.is_selected.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create_import(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        source_type: SearchConsoleSourceType,
        property_id: Optional[UUID] = None,
        filename: Optional[str] = None,
        date_start: Optional[datetime] = None,
        date_end: Optional[datetime] = None,
        comparison_window: Optional[GSCComparisonWindow] = None,
        metadata: Optional[dict] = None,
    ) -> SearchConsoleImport:
        import_record = SearchConsoleImport(
            tenant_id=tenant_id,
            project_id=project_id,
            property_id=property_id,
            source_type=source_type,
            status=SearchConsoleImportStatus.pending,
            filename=filename,
            date_start=date_start,
            date_end=date_end,
            comparison_window=comparison_window,
            rows_imported=0,
            metadata_json=metadata or {},
        )
        self.db.add(import_record)
        await self.db.flush()
        await self.db.refresh(import_record)
        return import_record

    async def get_import(self, import_id: UUID, tenant_id: UUID) -> Optional[SearchConsoleImport]:
        result = await self.db.execute(
            select(SearchConsoleImport).where(
                SearchConsoleImport.id == import_id,
                SearchConsoleImport.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_imports(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SearchConsoleImport]:
        query = select(SearchConsoleImport).where(SearchConsoleImport.tenant_id == tenant_id)
        if project_id:
            query = query.where(SearchConsoleImport.project_id == project_id)
        query = query.order_by(SearchConsoleImport.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def set_import_status(
        self,
        import_record: SearchConsoleImport,
        status: SearchConsoleImportStatus,
        error_message: Optional[str] = None,
    ) -> SearchConsoleImport:
        import_record.status = status
        import_record.error_message = error_message
        import_record.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(import_record)
        return import_record

    async def add_rows(self, records: Iterable[dict]) -> int:
        count = 0
        for values in records:
            self.db.add(SearchConsoleRow(**values))
            count += 1
        await self.db.flush()
        return count

    async def finish_import(self, import_record: SearchConsoleImport, rows_imported: int) -> SearchConsoleImport:
        import_record.rows_imported = rows_imported
        import_record.status = SearchConsoleImportStatus.completed
        import_record.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(import_record)
        return import_record

    async def list_rows(
        self,
        import_id: UUID,
        tenant_id: UUID,
        period: Optional[SearchConsolePeriod] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SearchConsoleRow]:
        query = select(SearchConsoleRow).where(SearchConsoleRow.import_id == import_id, SearchConsoleRow.tenant_id == tenant_id)
        if period:
            query = query.where(SearchConsoleRow.period == period)
        query = query.order_by(SearchConsoleRow.impressions.desc(), SearchConsoleRow.clicks.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def rows_for_analysis(self, import_id: UUID, tenant_id: UUID) -> List[SearchConsoleRow]:
        result = await self.db.execute(
            select(SearchConsoleRow).where(SearchConsoleRow.import_id == import_id, SearchConsoleRow.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def create_sync_job(
        self,
        tenant_id: UUID,
        project_id: UUID,
        connection_id: Optional[UUID],
        property_id: UUID,
        sync_type: GSCSyncType,
        date_start: datetime,
        date_end: datetime,
        comparison_window: GSCComparisonWindow,
        status: GSCSyncJobStatus = GSCSyncJobStatus.queued,
        error_message: Optional[str] = None,
    ) -> GSCSyncJob:
        job = GSCSyncJob(
            tenant_id=tenant_id,
            project_id=project_id,
            connection_id=connection_id,
            property_id=property_id,
            sync_type=sync_type,
            date_start=date_start,
            date_end=date_end,
            comparison_window=comparison_window,
            status=status,
            error_message=error_message,
        )
        if status in {GSCSyncJobStatus.completed, GSCSyncJobStatus.failed}:
            job.started_at = datetime.utcnow()
            job.completed_at = datetime.utcnow()
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def get_sync_job(self, job_id: UUID, tenant_id: Optional[UUID] = None) -> Optional[GSCSyncJob]:
        query = select(GSCSyncJob).where(GSCSyncJob.id == job_id)
        if tenant_id:
            query = query.where(GSCSyncJob.tenant_id == tenant_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_sync_jobs(
        self,
        project_id: UUID,
        tenant_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GSCSyncJob]:
        result = await self.db.execute(
            select(GSCSyncJob)
            .where(GSCSyncJob.project_id == project_id, GSCSyncJob.tenant_id == tenant_id)
            .order_by(GSCSyncJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_sync_job_status(
        self,
        job: GSCSyncJob,
        status: GSCSyncJobStatus,
        error_message: Optional[str] = None,
    ) -> GSCSyncJob:
        now = datetime.utcnow()
        job.status = status
        job.error_message = error_message
        job.updated_at = now
        if status == GSCSyncJobStatus.running and not job.started_at:
            job.started_at = now
        if status in {GSCSyncJobStatus.completed, GSCSyncJobStatus.failed}:
            job.completed_at = now
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def finish_sync_job(
        self,
        job: GSCSyncJob,
        import_id: UUID,
        rows_fetched: int,
        opportunities_created: int,
        opportunities_updated: int,
    ) -> GSCSyncJob:
        job.import_id = import_id
        job.rows_fetched = rows_fetched
        job.opportunities_created = opportunities_created
        job.opportunities_updated = opportunities_updated
        job.status = GSCSyncJobStatus.completed
        job.completed_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        prop = await self.get_property(job.property_id, job.tenant_id)
        if prop:
            prop.last_synced_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def match_pages_by_urls(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        urls: List[str],
    ) -> dict[str, CrawlPage]:
        if not urls:
            return {}
        query = select(CrawlPage).join(CrawlJob, CrawlJob.id == CrawlPage.crawl_job_id).where(CrawlJob.tenant_id == tenant_id)
        if project_id:
            query = query.where(CrawlJob.project_id == project_id)
        result = await self.db.execute(query)
        pages = list(result.scalars().all())
        by_url = {}
        for page in pages:
            for url in {page.url, page.normalized_url, page.final_url, page.canonical_url}:
                if url:
                    by_url[self._url_key(url)] = page
        return {url: by_url[self._url_key(url)] for url in urls if self._url_key(url) in by_url}

    async def signal_context(self, tenant_id: UUID, project_id: Optional[UUID], page_ids: List[UUID]) -> dict:
        if not page_ids:
            return {"issues": [], "seo_scores": [], "geo_scores": [], "content_suggestions": [], "internal_links": [], "blog_topics": []}
        issue_result = await self.db.execute(
            select(SEOIssue).where(
                SEOIssue.tenant_id == tenant_id,
                SEOIssue.status == SEOIssueStatus.open,
                SEOIssue.crawl_page_id.in_(page_ids),
            )
        )
        seo_result = await self.db.execute(
            select(SEOPageScore).where(SEOPageScore.tenant_id == tenant_id, SEOPageScore.crawl_page_id.in_(page_ids))
        )
        geo_result = await self.db.execute(
            select(GeoAeoPageScore).where(GeoAeoPageScore.tenant_id == tenant_id, GeoAeoPageScore.page_id.in_(page_ids))
        )
        content_result = await self.db.execute(
            select(ContentOptimizationSuggestion).where(
                ContentOptimizationSuggestion.tenant_id == tenant_id,
                ContentOptimizationSuggestion.page_id.in_(page_ids),
            )
        )
        link_result = await self.db.execute(
            select(InternalLinkRecommendation).where(
                InternalLinkRecommendation.tenant_id == tenant_id,
                or_(
                    InternalLinkRecommendation.source_page_id.in_(page_ids),
                    InternalLinkRecommendation.target_page_id.in_(page_ids),
                ),
            )
        )
        topic_query = select(BlogTopic).where(BlogTopic.tenant_id == tenant_id)
        if project_id:
            topic_query = topic_query.where(BlogTopic.project_id == project_id)
        topic_result = await self.db.execute(topic_query)
        return {
            "issues": list(issue_result.scalars().all()),
            "seo_scores": list(seo_result.scalars().all()),
            "geo_scores": list(geo_result.scalars().all()),
            "content_suggestions": list(content_result.scalars().all()),
            "internal_links": list(link_result.scalars().all()),
            "blog_topics": list(topic_result.scalars().all()),
        }

    async def find_open_opportunity(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        query: str,
        page_url: str,
        opportunity_type: SearchConsoleOpportunityType,
    ) -> Optional[SearchConsoleOpportunity]:
        result = await self.db.execute(
            select(SearchConsoleOpportunity).where(
                SearchConsoleOpportunity.tenant_id == tenant_id,
                SearchConsoleOpportunity.project_id == project_id,
                SearchConsoleOpportunity.query == query,
                SearchConsoleOpportunity.page_url == page_url,
                SearchConsoleOpportunity.opportunity_type == opportunity_type,
                SearchConsoleOpportunity.status.in_([
                    SearchConsoleOpportunityStatus.suggested,
                    SearchConsoleOpportunityStatus.approved,
                ]),
            )
        )
        return result.scalar_one_or_none()

    async def create_opportunity(self, values: dict) -> SearchConsoleOpportunity:
        opportunity = SearchConsoleOpportunity(**values)
        self.db.add(opportunity)
        await self.db.flush()
        await self.db.refresh(opportunity)
        return opportunity

    async def update_opportunity(self, opportunity: SearchConsoleOpportunity, values: dict) -> SearchConsoleOpportunity:
        for key, value in values.items():
            if key in {"id", "tenant_id", "project_id", "query", "page_url", "opportunity_type", "status"}:
                continue
            setattr(opportunity, key, value)
        opportunity.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(opportunity)
        return opportunity

    async def list_opportunities(
        self,
        tenant_id: UUID,
        import_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        status: Optional[SearchConsoleOpportunityStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SearchConsoleOpportunity]:
        query = select(SearchConsoleOpportunity).where(SearchConsoleOpportunity.tenant_id == tenant_id)
        if import_id:
            query = query.where(SearchConsoleOpportunity.import_id == import_id)
        if project_id:
            query = query.where(SearchConsoleOpportunity.project_id == project_id)
        if status:
            query = query.where(SearchConsoleOpportunity.status == status)
        query = query.order_by(
            SearchConsoleOpportunity.priority_score.desc(),
            SearchConsoleOpportunity.updated_at.desc(),
        ).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_opportunity(self, opportunity_id: UUID, tenant_id: UUID) -> Optional[SearchConsoleOpportunity]:
        result = await self.db.execute(
            select(SearchConsoleOpportunity).where(
                SearchConsoleOpportunity.id == opportunity_id,
                SearchConsoleOpportunity.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_opportunity_status(
        self,
        opportunity: SearchConsoleOpportunity,
        status: SearchConsoleOpportunityStatus,
    ) -> SearchConsoleOpportunity:
        now = datetime.utcnow()
        opportunity.status = status
        opportunity.updated_at = now
        if status == SearchConsoleOpportunityStatus.approved:
            opportunity.approved_at = now
        elif status == SearchConsoleOpportunityStatus.rejected:
            opportunity.rejected_at = now
        elif status == SearchConsoleOpportunityStatus.completed:
            opportunity.completed_at = now
        await self.db.flush()
        await self.db.refresh(opportunity)
        return opportunity

    async def summary(self, project_id: UUID, tenant_id: UUID) -> dict:
        imports_count = await self.db.scalar(
            select(func.count(SearchConsoleImport.id)).where(
                SearchConsoleImport.project_id == project_id,
                SearchConsoleImport.tenant_id == tenant_id,
            )
        )
        rows_count = await self.db.scalar(
            select(func.count(SearchConsoleRow.id)).where(
                SearchConsoleRow.project_id == project_id,
                SearchConsoleRow.tenant_id == tenant_id,
                SearchConsoleRow.period == SearchConsolePeriod.current,
            )
        )
        opportunities = await self.list_opportunities(tenant_id=tenant_id, project_id=project_id, limit=1000)
        by_status = {}
        by_type = {}
        for opp in opportunities:
            by_status[opp.status.value] = by_status.get(opp.status.value, 0) + 1
            by_type[opp.opportunity_type.value] = by_type.get(opp.opportunity_type.value, 0) + 1
        latest_job_result = await self.db.execute(
            select(GSCSyncJob)
            .where(GSCSyncJob.project_id == project_id, GSCSyncJob.tenant_id == tenant_id)
            .order_by(GSCSyncJob.created_at.desc())
            .limit(1)
        )
        latest_job = latest_job_result.scalar_one_or_none()
        selected_property = await self.selected_property(project_id, tenant_id)
        return {
            "project_id": project_id,
            "imports_count": int(imports_count or 0),
            "rows_count": int(rows_count or 0),
            "opportunities_count": len(opportunities),
            "opportunities_by_status": by_status,
            "opportunities_by_type": by_type,
            "latest_sync_job_id": latest_job.id if latest_job else None,
            "latest_sync_status": latest_job.status if latest_job else None,
            "selected_property": selected_property,
        }

    def _url_key(self, url: str) -> str:
        return (url or "").split("#", 1)[0].rstrip("/").lower()


def infer_gsc_property_type(site_url: str) -> GSCPropertyType:
    return GSCPropertyType.domain if str(site_url or "").startswith("sc-domain:") else GSCPropertyType.url_prefix
