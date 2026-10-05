"""Topic clusters, persisted as a graph rather than recomputed per request.

`SeoGrowthEngine.cluster_topics` already groups keywords into clusters, but the
result lived only in a response body: nothing could say which article belonged
to which pillar, which service page a cluster was meant to support, or which
part of a cluster was still missing. Writing it down is what turns "a list of
blog ideas" into a content structure.

Three node kinds, one table. A pillar, a supporting article and a service page
are the same thing structurally — a point in a topic graph — and splitting them
into separate tables would mean three joins to answer "what is in this cluster".
`node_type` carries the difference.

A node points at a `BlogTopic` (planned/written content) or a `CrawlPage` (a
page that already exists on the site), never both. That is what lets a cluster
show the gap between what the site has and what the topic actually needs.

Nothing here invents a cluster the data does not support; clusters are created
from measured opportunities, and a cluster with one node is still an honest
cluster of one.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class ClusterNodeType(str, enum.Enum):
    """What a point in the graph represents."""

    pillar = "pillar"                  # the broad guide everything links back to
    supporting = "supporting"          # an article covering one facet
    service_page = "service_page"      # an existing commercial page the cluster feeds
    missing = "missing"                # a gap: wanted, not yet written


class ClusterNodeStatus(str, enum.Enum):
    planned = "planned"
    drafted = "drafted"
    published = "published"
    #: Suppressed because another node already serves this intent.
    cannibalised = "cannibalised"


class ContentCluster(Base):
    """A pillar and everything meant to support it."""

    __tablename__ = "content_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name = Column(String(255), nullable=False)
    #: The normalised phrase the cluster is built around. Used for dedupe.
    pillar_topic = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    #: 0.0-1.0 — how much of the cluster actually exists on the site.
    coverage = Column(Float, nullable=False, default=0.0)
    #: Mirrors the Opportunity Score of the strongest member.
    priority_score = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    nodes = relationship(
        "ContentClusterNode", back_populates="cluster", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # One cluster per topic per project — the dedupe that stops a weekly
        # scan creating the same cluster every Monday.
        UniqueConstraint("project_id", "pillar_topic", name="uq_content_clusters_project_topic"),
        Index("ix_content_clusters_tenant_project", "tenant_id", "project_id"),
    )


class ContentClusterNode(Base):
    """One point in a cluster: an article, a page, or an acknowledged gap."""

    __tablename__ = "content_cluster_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cluster_id = Column(
        UUID(as_uuid=True), ForeignKey("content_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )

    node_type = Column(SQLEnum(ClusterNodeType), nullable=False, index=True)
    status = Column(
        SQLEnum(ClusterNodeStatus), nullable=False, default=ClusterNodeStatus.planned, index=True
    )

    title = Column(String(500), nullable=False)
    target_query = Column(String(500), nullable=True)
    search_intent = Column(String(32), nullable=True)

    #: Planned or written content. Mutually exclusive with crawl_page_id.
    blog_topic_id = Column(
        UUID(as_uuid=True), ForeignKey("blog_topics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: A page that already exists on the site.
    crawl_page_id = Column(
        UUID(as_uuid=True), ForeignKey("crawl_pages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    url = Column(String(2048), nullable=True)

    priority_score = Column(Float, nullable=False, default=0.0)
    #: Why this node is here, carried through to the dashboard.
    reason = Column(Text, nullable=True)
    #: Internal links this node should carry: [{to_node_id, anchor, why}].
    link_plan = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cluster = relationship("ContentCluster", back_populates="nodes")

    __table_args__ = (
        Index("ix_cluster_nodes_cluster_type", "cluster_id", "node_type"),
        # The same query must not appear twice in one cluster.
        UniqueConstraint("cluster_id", "title", name="uq_cluster_node_title"),
    )
