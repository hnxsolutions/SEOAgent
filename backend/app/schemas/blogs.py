"""Schemas for blog planning and draft generation."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.blog import BlogPlanStatus, BlogSearchIntent, BlogTopicStatus


class BlogPlanCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    target_site_url: Optional[str] = None
    project_id: Optional[UUID] = None
    blogs_per_week: int = Field(3, ge=1, le=20)


class BlogPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    target_site_url: Optional[str] = None
    status: str
    blogs_per_week: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class BlogPlanListResponse(BaseModel):
    plans: List[BlogPlanResponse]
    limit: int
    offset: int
    has_more: bool = False


class BlogTopicGenerateRequest(BaseModel):
    count: Optional[int] = Field(None, ge=1, le=20)


class BlogTopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    blog_plan_id: UUID
    target_keyword: str
    search_intent: str
    title: str
    angle: Optional[str] = None
    target_audience: Optional[str] = None
    target_landing_page_id: Optional[UUID] = None
    priority_score: float
    status: str
    reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    drafted_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


class BlogTopicListResponse(BaseModel):
    topics: List[BlogTopicResponse]
    limit: int
    offset: int
    has_more: bool = False


class BlogDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID
    tenant_id: UUID
    project_id: Optional[UUID] = None
    blog_topic_id: UUID
    title: str
    slug: str
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    outline: Optional[Dict[str, Any]] = None
    draft_markdown: str
    faq_json: Optional[List[Dict[str, Any]]] = None
    schema_json: Optional[Dict[str, Any]] = None
    internal_link_plan: Optional[List[Dict[str, Any]]] = None
    knowledge_sources_used: Optional[List[Dict[str, Any]]] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


class BlogDraftListResponse(BaseModel):
    drafts: List[BlogDraftResponse]
    limit: int
    offset: int
    has_more: bool = False
