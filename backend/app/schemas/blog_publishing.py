"""Schemas for safe blog publishing and blog infrastructure workflows."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.blog_publishing import (
    BlogInfrastructureStrategy,
    BlogPublishConnectionStatus,
    BlogPublishProvider,
)


class BlogPublishConnectionCreate(BaseModel):
    project_id: UUID
    provider: BlogPublishProvider
    site_url: Optional[str] = None
    repo_connection_id: Optional[UUID] = None
    export_folder_path: Optional[str] = None
    username: Optional[str] = None
    app_password: Optional[str] = None
    auto_upload_drafts_enabled: bool = False
    auto_publish_enabled: bool = False


class BlogPublishConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    provider: str
    site_url: Optional[str] = None
    repo_connection_id: Optional[UUID] = None
    export_folder_path: Optional[str] = None
    username: Optional[str] = None
    status: str
    auto_upload_drafts_enabled: bool
    auto_publish_enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class BlogPublishConnectionListResponse(BaseModel):
    connections: List[BlogPublishConnectionResponse]
    limit: int
    offset: int
    has_more: bool = False


class BlogPublishConnectionTestResponse(BaseModel):
    connection_id: UUID
    provider: str
    status: str
    ok: bool
    message: str


class BlogInfrastructureCheckRequest(BaseModel):
    repo_connection_id: Optional[UUID] = None


class BlogInfrastructureCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    repo_connection_id: Optional[UUID] = None
    status: str
    framework_detected: Optional[str] = None
    has_blog_index: bool
    has_blog_detail_route: bool
    has_content_directory: bool
    blog_route_path: Optional[str] = None
    content_directory: Optional[str] = None
    recommended_strategy: str
    issues: Optional[List[Dict[str, Any]]] = None
    created_at: datetime


class MarkdownExportRequest(BaseModel):
    connection_id: Optional[UUID] = None
    export_folder_path: Optional[str] = None
    overwrite: bool = False


class WordPressDraftRequest(BaseModel):
    connection_id: UUID


class NextJsBlogPatchRequest(BaseModel):
    connection_id: Optional[UUID] = None
    repo_connection_id: Optional[UUID] = None
    content_directory: Optional[str] = None
    extension: str = Field("md", pattern="^(md|mdx)$")
    overwrite: bool = False


class BlogInfrastructurePatchRequest(BaseModel):
    connection_id: Optional[UUID] = None
    repo_connection_id: Optional[UUID] = None
    strategy: BlogInfrastructureStrategy = BlogInfrastructureStrategy.nextjs_markdown


class BlogPublishRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    blog_draft_id: Optional[UUID] = None
    connection_id: Optional[UUID] = None
    provider: str
    mode: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime


class BlogPublishResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    publish_run_id: UUID
    blog_draft_id: Optional[UUID] = None
    provider: str
    status: str
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    file_path: Optional[str] = None
    patch_id: Optional[UUID] = None
    pr_id: Optional[UUID] = None
    title: Optional[str] = None
    slug: Optional[str] = None
    created_at: datetime


class BlogPublishActionResponse(BaseModel):
    run: BlogPublishRunResponse
    result: Optional[BlogPublishResultResponse] = None
