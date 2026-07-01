"""
SEO Agent SaaS - SERP Analysis Service
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional, List
from uuid import UUID
from datetime import datetime
import structlog

from app.models.serp import SERPAnalysis, SERPStatus

logger = structlog.get_logger(__name__)


class SERPService:
    """SERP analysis service"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_analysis(
        self,
        keywords: List[str],
        location: str = "us",
        language: str = "en",
        search_engine: str = "google",
        tenant_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None
    ) -> SERPAnalysis:
        """Create a new SERP analysis job"""
        analysis = SERPAnalysis(
            keywords=keywords,
            total_keywords=len(keywords),
            location=location,
            language=language,
            search_engine=search_engine,
            tenant_id=tenant_id,
            project_id=project_id,
            status=SERPStatus.pending,
        )
        self.db.add(analysis)
        await self.db.commit()
        await self.db.refresh(analysis)
        return analysis
    
    async def get_analysis_status(
        self,
        analysis_id: UUID,
        tenant_id: UUID
    ) -> Optional[SERPAnalysis]:
        """Get SERP analysis status"""
        result = await self.db.execute(
            select(SERPAnalysis)
            .options(selectinload(SERPAnalysis.results))
            .where(
                SERPAnalysis.id == analysis_id,
                SERPAnalysis.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()
    
    async def get_tenant_analyses(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID] = None
    ) -> List[SERPAnalysis]:
        """Get all SERP analyses for a tenant"""
        query = select(SERPAnalysis).where(SERPAnalysis.tenant_id == tenant_id)
        if project_id:
            query = query.where(SERPAnalysis.project_id == project_id)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def execute_analysis(
        self,
        analysis_id: UUID,
        keywords: List[str]
    ):
        """Mark automated SERP analysis as unavailable.

        The previous MVP path wrote sample SERP rows. That made the dashboard
        look successful with non-real ranking data, so keep the job record but
        fail it explicitly until a real provider-backed implementation exists.
        """
        # Update status to running
        analysis = await self.db.get(SERPAnalysis, analysis_id)
        if not analysis:
            logger.error(f"SERP analysis {analysis_id} not found")
            return
        
        analysis.status = SERPStatus.running
        analysis.started_at = datetime.utcnow()
        await self.db.commit()
        
        message = (
            "Automated SERP analysis is not implemented in the local MVP. "
            "Use manual SERP snapshots or Search Console rank tracking for real data."
        )
        logger.warning(message, analysis_id=str(analysis_id), keyword_count=len(keywords))
        analysis.status = SERPStatus.failed
        analysis.error_message = message
        analysis.progress = 100
        analysis.completed_at = datetime.utcnow()
        await self.db.commit()
