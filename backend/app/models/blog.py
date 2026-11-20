"""Blog planning and draft models for local SEO content workflows."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class BlogPlanStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    completed = "completed"


class BlogSearchIntent(str, enum.Enum):
    informational = "informational"
    commercial = "commercial"
    transactional = "transactional"
    local = "local"
    comparison = "comparison"


class BlogTopicStatus(str, enum.Enum):
    suggested = "suggested"
    approved = "approved"
    rejected = "rejected"
    drafted = "drafted"
    published = "published"


class BlogDraftStatus(str, enum.Enum):
    """The life of one article, from an idea to something being measured.

    The first four values predate this workflow and keep their exact spelling,
    so every existing row stays valid and no backfill is needed. The rest name
    the stages that were previously invisible — an article sitting in `draft`
    could equally have been unwritten, written but unchecked, or checked and
    waiting for a person, and nothing could tell them apart.

    `rejected` is deliberately reachable from anywhere and goes nowhere: a
    rejected article is finished, not parked.
    """

    idea = "idea"
    researched = "researched"
    outline = "outline"
    draft = "draft"
    seo_validated = "seo_validated"
    pending_approval = "pending_approval"
    approved = "approved"
    published = "published"
    monitoring = "monitoring"
    rejected = "rejected"


#: The only moves allowed, as {from: {to, ...}}.
#:
#: Enforced in the service rather than by the database because the useful
#: failure is an API error naming the attempted move, not an integrity error.
#: The rule that matters: nothing reaches `published` except from `approved`,
#: so no path — autonomous or otherwise — publishes without a human.
BLOG_DRAFT_TRANSITIONS: dict[str, set[str]] = {
    "idea": {"researched", "rejected"},
    "researched": {"outline", "rejected"},
    "outline": {"draft", "rejected"},
    "draft": {"seo_validated", "outline", "rejected"},
    "seo_validated": {"pending_approval", "draft", "rejected"},
    "pending_approval": {"approved", "rejected", "draft"},
    "approved": {"published", "rejected"},
    "published": {"monitoring"},
    "monitoring": {"pending_approval"},  # a refresh re-enters the approval loop
    "rejected": set(),
}


def can_transition(current: str, target: str) -> bool:
    """Whether this move is legal. Unknown states are never legal."""
    return target in BLOG_DRAFT_TRANSITIONS.get(str(current), set())


class BlogPlan(Base):
    """A buyer-intent blog planning workspace for a tenant/project."""

    __tablename__ = "blog_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_site_url = Column(String(2048), nullable=True)
    status = Column(SQLEnum(BlogPlanStatus), default=BlogPlanStatus.draft, nullable=False, index=True)
    blogs_per_week = Column(Integer, default=3)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    topics = relationship("BlogTopic", back_populates="blog_plan", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_blog_plans_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_plans_created", "created_at", postgresql_using="brin"),
    )


class BlogTopic(Base):
    """A planned blog topic generated from site and knowledge signals."""

    __tablename__ = "blog_topics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    blog_plan_id = Column(UUID(as_uuid=True), ForeignKey("blog_plans.id"), nullable=False, index=True)

    target_keyword = Column(String(255), nullable=False, index=True)
    search_intent = Column(SQLEnum(BlogSearchIntent), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    angle = Column(Text, nullable=True)
    target_audience = Column(String(255), nullable=True)
    target_landing_page_id = Column(UUID(as_uuid=True), ForeignKey("crawl_pages.id"), nullable=True, index=True)
    priority_score = Column(Float, nullable=False)
    status = Column(SQLEnum(BlogTopicStatus), default=BlogTopicStatus.suggested, nullable=False, index=True)
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    drafted_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)

    blog_plan = relationship("BlogPlan", back_populates="topics")
    drafts = relationship("BlogDraft", back_populates="blog_topic", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_blog_topics_plan_status", "blog_plan_id", "status"),
        Index("ix_blog_topics_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_topics_priority", "priority_score"),
        Index("ix_blog_topics_dedupe", "tenant_id", "blog_plan_id", "target_keyword", unique=True),
    )


class BlogDraft(Base):
    """A markdown blog draft generated from approved topics and knowledge chunks."""

    __tablename__ = "blog_drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    blog_topic_id = Column(UUID(as_uuid=True), ForeignKey("blog_topics.id"), nullable=False, index=True)

    title = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, index=True)
    meta_title = Column(String(255), nullable=True)
    meta_description = Column(Text, nullable=True)
    outline = Column(JSONB, nullable=True)
    draft_markdown = Column(Text, nullable=False)
    faq_json = Column(JSONB, nullable=True)
    schema_json = Column(JSONB, nullable=True)
    internal_link_plan = Column(JSONB, nullable=True)
    knowledge_sources_used = Column(JSONB, nullable=True)
    status = Column(SQLEnum(BlogDraftStatus), default=BlogDraftStatus.draft, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)

    blog_topic = relationship("BlogTopic", back_populates="drafts")

    __table_args__ = (
        Index("ix_blog_drafts_tenant_project", "tenant_id", "project_id"),
        Index("ix_blog_drafts_topic_status", "blog_topic_id", "status"),
        Index("ix_blog_drafts_created", "created_at", postgresql_using="brin"),
    )
