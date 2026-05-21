"""Repository helpers for SEO copy review."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog import BlogDraft
from app.models.content_optimization import ContentOptimizationSuggestion
from app.models.copy_review import (
    SeoCopyApprovalReadiness,
    SeoCopyComplianceProfile,
    SeoCopyPolicy,
    SeoCopyReview,
    SeoCopyRevision,
    SeoCopyRevisionStatus,
)
from app.models.project import Project
from app.models.repo_agent import RepoConnection, SeoCodePatch

POSTGRES_TEXT_CODECS = {
    "UTF8": "utf-8",
    "UNICODE": "utf-8",
    "WIN1252": "cp1252",
    "LATIN1": "latin1",
}


class SeoCopyReviewRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_project(self, project_id: UUID, tenant_id: UUID) -> Optional[Project]:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_policy(self, project_id: Optional[UUID], tenant_id: UUID) -> Optional[SeoCopyPolicy]:
        if not project_id:
            return None
        result = await self.db.execute(
            select(SeoCopyPolicy).where(
                SeoCopyPolicy.project_id == project_id,
                SeoCopyPolicy.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_policy(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        compliance_profile: SeoCopyComplianceProfile,
        blocked_phrases: Optional[list[str]] = None,
        allowed_topics: Optional[list[str]] = None,
        notes: Optional[str] = None,
    ) -> SeoCopyPolicy:
        encoding = await self._server_encoding()
        policy = await self.get_policy(project_id, tenant_id)
        if policy:
            policy.compliance_profile = compliance_profile
            policy.blocked_phrases = self._sanitize_value(blocked_phrases, encoding)
            policy.allowed_topics = self._sanitize_value(allowed_topics, encoding)
            policy.notes = self._sanitize_text(notes, encoding)
            policy.updated_at = datetime.utcnow()
        else:
            policy = SeoCopyPolicy(
                tenant_id=tenant_id,
                project_id=project_id,
                compliance_profile=compliance_profile,
                blocked_phrases=self._sanitize_value(blocked_phrases, encoding),
                allowed_topics=self._sanitize_value(allowed_topics, encoding),
                notes=self._sanitize_text(notes, encoding),
            )
            self.db.add(policy)
        await self.db.flush()
        await self.db.refresh(policy)
        return policy

    async def create_review(self, values: dict) -> SeoCopyReview:
        review = SeoCopyReview(**await self._sanitize_for_database_encoding(values))
        self.db.add(review)
        await self.db.flush()
        await self.db.refresh(review)
        return review

    async def list_reviews(
        self,
        project_id: UUID,
        tenant_id: UUID,
        readiness: Optional[SeoCopyApprovalReadiness] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SeoCopyReview]:
        query = select(SeoCopyReview).where(
            SeoCopyReview.project_id == project_id,
            SeoCopyReview.tenant_id == tenant_id,
        )
        if readiness:
            query = query.where(SeoCopyReview.approval_readiness == readiness)
        query = query.order_by(SeoCopyReview.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_review(self, review_id: UUID, tenant_id: UUID) -> Optional[SeoCopyReview]:
        result = await self.db.execute(
            select(SeoCopyReview).where(SeoCopyReview.id == review_id, SeoCopyReview.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def update_review_readiness(
        self,
        review: SeoCopyReview,
        readiness: SeoCopyApprovalReadiness,
        notes: Optional[str] = None,
    ) -> SeoCopyReview:
        review.approval_readiness = readiness
        if notes is not None:
            review.revision_notes = notes
        review.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(review)
        return review

    async def create_revision(self, values: dict) -> SeoCopyRevision:
        revision = SeoCopyRevision(**await self._sanitize_for_database_encoding(values))
        self.db.add(revision)
        await self.db.flush()
        await self.db.refresh(revision)
        return revision

    async def latest_revision(self, review_id: UUID, tenant_id: UUID) -> Optional[SeoCopyRevision]:
        result = await self.db.execute(
            select(SeoCopyRevision)
            .where(SeoCopyRevision.review_id == review_id, SeoCopyRevision.tenant_id == tenant_id)
            .order_by(SeoCopyRevision.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_revision_status(
        self,
        revision: SeoCopyRevision,
        status: SeoCopyRevisionStatus,
    ) -> SeoCopyRevision:
        revision.status = status
        revision.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(revision)
        return revision

    async def get_repo_patch(self, patch_id: UUID, tenant_id: UUID) -> Optional[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch).where(SeoCodePatch.id == patch_id, SeoCodePatch.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_repo_connection(self, connection_id: UUID, tenant_id: UUID) -> Optional[RepoConnection]:
        result = await self.db.execute(
            select(RepoConnection).where(RepoConnection.id == connection_id, RepoConnection.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_repo_patches_for_scan(self, scan_id: UUID, tenant_id: UUID, limit: int = 1000) -> list[SeoCodePatch]:
        result = await self.db.execute(
            select(SeoCodePatch)
            .where(SeoCodePatch.scan_run_id == scan_id, SeoCodePatch.tenant_id == tenant_id)
            .order_by(SeoCodePatch.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_repo_patch_content(
        self,
        patch: SeoCodePatch,
        proposed_content: str,
        diff_text: str,
        explanation: str,
    ) -> SeoCodePatch:
        encoding = await self._server_encoding()
        patch.proposed_content = self._sanitize_text(proposed_content, encoding)
        patch.diff_text = self._sanitize_text(diff_text, encoding)
        patch.explanation = self._sanitize_text(explanation, encoding)
        patch.updated_at = datetime.utcnow()
        await self.db.flush()
        await self.db.refresh(patch)
        return patch

    async def get_content_suggestion(
        self,
        suggestion_id: UUID,
        tenant_id: UUID,
    ) -> Optional[ContentOptimizationSuggestion]:
        result = await self.db.execute(
            select(ContentOptimizationSuggestion).where(
                ContentOptimizationSuggestion.id == suggestion_id,
                ContentOptimizationSuggestion.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_blog_draft(self, draft_id: UUID, tenant_id: UUID) -> Optional[BlogDraft]:
        result = await self.db.execute(
            select(BlogDraft).where(BlogDraft.id == draft_id, BlogDraft.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def _sanitize_for_database_encoding(self, value):
        encoding = await self._server_encoding()
        return self._sanitize_value(value, encoding)

    async def _server_encoding(self) -> str:
        encoding = self.db.info.get("server_encoding")
        if encoding:
            return str(encoding)
        result = await self.db.execute(text("select current_setting('server_encoding')"))
        encoding = str(result.scalar_one_or_none() or "UTF8").upper()
        self.db.info["server_encoding"] = encoding
        return encoding

    def _sanitize_value(self, value, encoding: str):
        if isinstance(value, str):
            return self._sanitize_text(value, encoding)
        if isinstance(value, list):
            return [self._sanitize_value(item, encoding) for item in value]
        if isinstance(value, tuple):
            return tuple(self._sanitize_value(item, encoding) for item in value)
        if isinstance(value, dict):
            return {
                self._sanitize_value(key, encoding) if isinstance(key, str) else key:
                self._sanitize_value(item, encoding)
                for key, item in value.items()
            }
        return value

    def _sanitize_text(self, value: Optional[str], encoding: str) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.replace("\x00", "")
        if encoding.upper() in {"UTF8", "UNICODE"}:
            return cleaned
        codec = POSTGRES_TEXT_CODECS.get(encoding.upper(), encoding.lower())
        try:
            return cleaned.encode(codec, errors="ignore").decode(codec, errors="ignore")
        except LookupError:
            return cleaned.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
