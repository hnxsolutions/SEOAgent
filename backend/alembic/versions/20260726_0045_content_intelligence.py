"""Website knowledge profiles, content clusters, refresh proposals, 9-state drafts.

Four additions that together let the agent remember what it worked out, instead
of recomputing it per request and forgetting it afterwards:

* `website_profiles` (+ snapshots) — what the agent understands about the site,
  with per-field provenance so inference is never shown as fact.
* `content_clusters` / `content_cluster_nodes` — the topic graph, persisted.
* `content_refresh_proposals` — a detected decline, waiting for approval.
* six new `blogdraftstatus` values completing the 9-state workflow.

The enum keeps its four existing values untouched, so every existing draft row
stays valid and nothing needs backfilling.

Revision ID: 0045_content_intelligence
Revises: 0044_autonomous_schedules
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045_content_intelligence"
down_revision: Union[str, None] = "0044_autonomous_schedules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_DRAFT_STATES = (
    "idea",
    "researched",
    "outline",
    "seo_validated",
    "pending_approval",
    "monitoring",
)


def upgrade() -> None:
    # --- 9-state blog workflow -------------------------------------------
    # ALTER TYPE ... ADD VALUE cannot share a transaction with the DDL below
    # on older servers, so commit first — the same pattern 0019 and 0044 use.
    op.execute("COMMIT")
    for value in NEW_DRAFT_STATES:
        op.execute(f"ALTER TYPE blogdraftstatus ADD VALUE IF NOT EXISTS '{value}'")

    profile_status = postgresql.ENUM(
        "pending", "completed", "failed", name="websiteprofilestatus", create_type=False
    )
    node_type = postgresql.ENUM(
        "pillar", "supporting", "service_page", "missing", name="clusternodetype", create_type=False
    )
    node_status = postgresql.ENUM(
        "planned", "drafted", "published", "cannibalised", name="clusternodestatus", create_type=False
    )
    refresh_status = postgresql.ENUM(
        "detected", "pending_approval", "approved", "rejected", "applied", "verified",
        name="refreshstatus", create_type=False,
    )
    refresh_reason = postgresql.ENUM(
        "declining_impressions", "declining_clicks", "position_drop", "low_ctr",
        "new_queries", "thin_coverage", "cannibalisation", "outdated",
        name="refreshreason", create_type=False,
    )

    bind = op.get_bind()
    for enum_type in (profile_status, node_type, node_status, refresh_status, refresh_reason):
        enum_type.create(bind, checkfirst=True)

    # --- website knowledge profile ---------------------------------------
    op.create_table(
        "website_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", profile_status, nullable=False, server_default="pending"),
        sa.Column("business_name", sa.String(length=255), nullable=True),
        sa.Column("business_type", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=120), nullable=True),
        sa.Column("niche", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("services", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("products", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("locations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("primary_topics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("brand_terms", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("important_pages", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("field_sources", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("field_confidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("field_evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("used_llm", sa.String(length=16), nullable=False, server_default="no"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", name="uq_website_profiles_project"),
    )
    op.create_index("ix_website_profiles_tenant_id", "website_profiles", ["tenant_id"])
    op.create_index("ix_website_profiles_status", "website_profiles", ["status"])
    op.create_index("ix_website_profiles_content_hash", "website_profiles", ["content_hash"])
    op.create_index("ix_website_profiles_tenant_project", "website_profiles", ["tenant_id", "project_id"])
    op.create_index("ix_website_profiles_created_at", "website_profiles", ["created_at"])

    op.create_table(
        "website_profile_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["website_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", "version", name="uq_profile_snapshot_version"),
    )
    op.create_index("ix_profile_snapshots_tenant_id", "website_profile_snapshots", ["tenant_id"])
    op.create_index("ix_profile_snapshots_project_id", "website_profile_snapshots", ["project_id"])
    op.create_index("ix_profile_snapshots_profile_id", "website_profile_snapshots", ["profile_id"])
    op.create_index("ix_profile_snapshots_created_at", "website_profile_snapshots", ["created_at"])

    # --- content clusters -------------------------------------------------
    op.create_table(
        "content_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("pillar_topic", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "pillar_topic", name="uq_content_clusters_project_topic"),
    )
    op.create_index("ix_content_clusters_tenant_id", "content_clusters", ["tenant_id"])
    op.create_index("ix_content_clusters_project_id", "content_clusters", ["project_id"])
    op.create_index("ix_content_clusters_tenant_project", "content_clusters", ["tenant_id", "project_id"])
    op.create_index("ix_content_clusters_created_at", "content_clusters", ["created_at"])

    op.create_table(
        "content_cluster_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_type", node_type, nullable=False),
        sa.Column("status", node_status, nullable=False, server_default="planned"),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("target_query", sa.String(length=500), nullable=True),
        sa.Column("search_intent", sa.String(length=32), nullable=True),
        sa.Column("blog_topic_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("crawl_page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("link_plan", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["cluster_id"], ["content_clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_topic_id"], ["blog_topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("cluster_id", "title", name="uq_cluster_node_title"),
    )
    op.create_index("ix_cluster_nodes_tenant_id", "content_cluster_nodes", ["tenant_id"])
    op.create_index("ix_cluster_nodes_cluster_id", "content_cluster_nodes", ["cluster_id"])
    op.create_index("ix_cluster_nodes_node_type", "content_cluster_nodes", ["node_type"])
    op.create_index("ix_cluster_nodes_status", "content_cluster_nodes", ["status"])
    op.create_index("ix_cluster_nodes_blog_topic_id", "content_cluster_nodes", ["blog_topic_id"])
    op.create_index("ix_cluster_nodes_crawl_page_id", "content_cluster_nodes", ["crawl_page_id"])
    op.create_index("ix_cluster_nodes_cluster_type", "content_cluster_nodes", ["cluster_id", "node_type"])
    op.create_index("ix_cluster_nodes_created_at", "content_cluster_nodes", ["created_at"])

    # --- refresh proposals ------------------------------------------------
    op.create_table(
        "content_refresh_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blog_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_url", sa.String(length=2048), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("reason", refresh_reason, nullable=False),
        sa.Column("status", refresh_status, nullable=False, server_default="detected"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("proposed_changes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blog_draft_id"], ["blog_drafts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_refresh_tenant_id", "content_refresh_proposals", ["tenant_id"])
    op.create_index("ix_refresh_project_id", "content_refresh_proposals", ["project_id"])
    op.create_index("ix_refresh_blog_draft_id", "content_refresh_proposals", ["blog_draft_id"])
    op.create_index("ix_refresh_reason", "content_refresh_proposals", ["reason"])
    op.create_index("ix_refresh_status", "content_refresh_proposals", ["status"])
    op.create_index("ix_refresh_detected_at", "content_refresh_proposals", ["detected_at"])
    op.create_index("ix_refresh_created_at", "content_refresh_proposals", ["created_at"])
    op.create_index("ix_refresh_tenant_status", "content_refresh_proposals", ["tenant_id", "status"])
    op.create_index("ix_refresh_project_priority", "content_refresh_proposals", ["project_id", "priority"])

    # One OPEN proposal per article per reason. Without it a weekly job raises
    # the same "impressions are down" finding every Friday until somebody acts,
    # and the approval queue becomes unreadable. Partial, so resolved proposals
    # stay in history and a later recurrence can be raised again.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_refresh_open_per_article_reason
        ON content_refresh_proposals (project_id, blog_draft_id, reason)
        WHERE status IN ('detected', 'pending_approval')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_refresh_open_per_article_reason")
    op.drop_table("content_refresh_proposals")
    op.drop_table("content_cluster_nodes")
    op.drop_table("content_clusters")
    op.drop_table("website_profile_snapshots")
    op.drop_table("website_profiles")
    for name in ("refreshreason", "refreshstatus", "clusternodestatus", "clusternodetype", "websiteprofilestatus"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
    # blogdraftstatus values are left in place: dropping one fails for any row
    # still using it, and an unused enum value costs nothing.
