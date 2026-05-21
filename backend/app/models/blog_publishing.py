"""Blog publishing and infrastructure models.

These records keep publishing actions reviewable and draft-only. They do not
auto-publish live posts, apply repo patches, merge PRs, or deploy sites.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class BlogPublishProvider(str, enum.Enum):
    wordpress = "wordpress"
    nextjs_repo = "nextjs_repo"
    markdown_export = "markdown_export"


class BlogPublishConnectionStatus(str, enum.Enum):
    connected = "connected"
    unavailable = "unavailable"
    failed = "failed"


class BlogInfrastructureCheckStatus(str, enum.Enum):
    completed = "completed"
    failed = "failed"


class BlogInfrastructureStrategy(str, enum.Enum):
    wordpress = "wordpress"
    nextjs_mdx = "nextjs_mdx"
    nextjs_markdown = "nextjs_markdown"
    markdown_export = "markdown_export"
    create_blog_infrastructure = "create_blog_infrastructure"


class BlogPublishMode(str, enum.Enum):
    draft_upload = "draft_upload"
    markdown_export = "markdown_export"
    repo_patch = "repo_patch"
    infrastructure_patch = "infrastructure_patch"


class BlogPublishRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    rolled_back = "rolled_back"


class BlogPublishResultStatus(str, enum.Enum):
    draft_created = "draft_created"
    file_exported = "file_exported"
    patch_created = "patch_created"
    infrastructure_patch_created = "infrastructure_patch_created"
    failed = "failed"


class BlogPublishConnection(Base):
    """A safe draft/export destination for approved blog drafts."""

    __tablename__ = "blog_publish_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    provider = Column(SQLEnum(BlogPublishProvider), nullable=False, index=True)
    site_url = Column(String(2048), nullable=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=True, index=True)
    export_folder_path = Column(String(2048), nullable=True)
    username = Column(String(255), nullable=True)
    encrypted_app_password = Column(Text, nullable=True)
    status = Column(
        SQLEnum(BlogPublishConnectionStatus),
        default=BlogPublishConnectionStatus.unavailable,
        nullable=False,
        index=True,
    )
    auto_upload_drafts_enabled = Column(Boolean, default=False, nullable=False)
    auto_publish_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_blog_publish_connections_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_publish_connections_project_provider", "tenant_id", "project_id", "provider"),
    )


class BlogInfrastructureCheck(Base):
    """Latest repository blog infrastructure detection result."""

    __tablename__ = "blog_infrastructure_checks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=True, index=True)
    status = Column(SQLEnum(BlogInfrastructureCheckStatus), nullable=False, index=True)
    framework_detected = Column(String(255), nullable=True)
    has_blog_index = Column(Boolean, default=False, nullable=False)
    has_blog_detail_route = Column(Boolean, default=False, nullable=False)
    has_content_directory = Column(Boolean, default=False, nullable=False)
    blog_route_path = Column(String(512), nullable=True)
    content_directory = Column(String(512), nullable=True)
    recommended_strategy = Column(SQLEnum(BlogInfrastructureStrategy), nullable=False, index=True)
    issues = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_blog_infrastructure_checks_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_infrastructure_checks_repo_created", "repo_connection_id", "created_at"),
    )


class BlogPublishRun(Base):
    """One controlled blog publishing/export attempt."""

    __tablename__ = "blog_publish_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    blog_draft_id = Column(UUID(as_uuid=True), ForeignKey("blog_drafts.id"), nullable=True, index=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("blog_publish_connections.id"), nullable=True, index=True)
    provider = Column(SQLEnum(BlogPublishProvider), nullable=False, index=True)
    mode = Column(SQLEnum(BlogPublishMode), nullable=False, index=True)
    status = Column(SQLEnum(BlogPublishRunStatus), default=BlogPublishRunStatus.queued, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_blog_publish_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_publish_runs_draft_status", "blog_draft_id", "status"),
    )


class BlogPublishResult(Base):
    """Result produced by a controlled blog publishing/export run."""

    __tablename__ = "blog_publish_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    publish_run_id = Column(UUID(as_uuid=True), ForeignKey("blog_publish_runs.id"), nullable=False, index=True)
    blog_draft_id = Column(UUID(as_uuid=True), ForeignKey("blog_drafts.id"), nullable=True, index=True)
    provider = Column(SQLEnum(BlogPublishProvider), nullable=False, index=True)
    status = Column(SQLEnum(BlogPublishResultStatus), nullable=False, index=True)
    external_id = Column(String(255), nullable=True)
    external_url = Column(String(2048), nullable=True)
    file_path = Column(String(2048), nullable=True)
    patch_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_patches.id"), nullable=True, index=True)
    pr_id = Column(UUID(as_uuid=True), ForeignKey("pull_request_records.id"), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    slug = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_blog_publish_results_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_publish_results_run_status", "publish_run_id", "status"),
    )
