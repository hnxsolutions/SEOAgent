"""Add blog planner and draft tables.

Revision ID: 0008_blog_planner
Revises: 0007_knowledge_base
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008_blog_planner"
down_revision: Union[str, None] = "0007_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


plan_status = postgresql.ENUM("draft", "active", "completed", name="blogplanstatus", create_type=False)
search_intent = postgresql.ENUM(
    "informational",
    "commercial",
    "transactional",
    "local",
    "comparison",
    name="blogsearchintent",
    create_type=False,
)
topic_status = postgresql.ENUM(
    "suggested",
    "approved",
    "rejected",
    "drafted",
    "published",
    name="blogtopicstatus",
    create_type=False,
)
draft_status = postgresql.ENUM(
    "draft",
    "approved",
    "rejected",
    "published",
    name="blogdraftstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    plan_status.create(bind, checkfirst=True)
    search_intent.create(bind, checkfirst=True)
    topic_status.create(bind, checkfirst=True)
    draft_status.create(bind, checkfirst=True)

    op.create_table(
        "blog_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_site_url", sa.String(length=2048), nullable=True),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("blogs_per_week", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blog_plans_tenant_id", "blog_plans", ["tenant_id"])
    op.create_index("ix_blog_plans_project_id", "blog_plans", ["project_id"])
    op.create_index("ix_blog_plans_status", "blog_plans", ["status"])
    op.create_index("ix_blog_plans_created_at", "blog_plans", ["created_at"])
    op.create_index("ix_blog_plans_tenant_project", "blog_plans", ["tenant_id", "project_id"])
    op.create_index("ix_blog_plans_created", "blog_plans", ["created_at"], postgresql_using="brin")

    op.create_table(
        "blog_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blog_plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_keyword", sa.String(length=255), nullable=False),
        sa.Column("search_intent", search_intent, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("angle", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.String(length=255), nullable=True),
        sa.Column("target_landing_page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("status", topic_status, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("drafted_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["blog_plan_id"], ["blog_plans.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["target_landing_page_id"], ["crawl_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blog_topics_tenant_id", "blog_topics", ["tenant_id"])
    op.create_index("ix_blog_topics_project_id", "blog_topics", ["project_id"])
    op.create_index("ix_blog_topics_blog_plan_id", "blog_topics", ["blog_plan_id"])
    op.create_index("ix_blog_topics_target_keyword", "blog_topics", ["target_keyword"])
    op.create_index("ix_blog_topics_search_intent", "blog_topics", ["search_intent"])
    op.create_index("ix_blog_topics_target_landing_page_id", "blog_topics", ["target_landing_page_id"])
    op.create_index("ix_blog_topics_status", "blog_topics", ["status"])
    op.create_index("ix_blog_topics_created_at", "blog_topics", ["created_at"])
    op.create_index("ix_blog_topics_plan_status", "blog_topics", ["blog_plan_id", "status"])
    op.create_index("ix_blog_topics_tenant_project", "blog_topics", ["tenant_id", "project_id"])
    op.create_index("ix_blog_topics_priority", "blog_topics", ["priority_score"])
    op.create_index("ix_blog_topics_dedupe", "blog_topics", ["tenant_id", "blog_plan_id", "target_keyword"], unique=True)

    op.create_table(
        "blog_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("blog_topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("meta_title", sa.String(length=255), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("outline", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_markdown", sa.Text(), nullable=False),
        sa.Column("faq_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("internal_link_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("knowledge_sources_used", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", draft_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["blog_topic_id"], ["blog_topics.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_blog_drafts_tenant_id", "blog_drafts", ["tenant_id"])
    op.create_index("ix_blog_drafts_project_id", "blog_drafts", ["project_id"])
    op.create_index("ix_blog_drafts_blog_topic_id", "blog_drafts", ["blog_topic_id"])
    op.create_index("ix_blog_drafts_slug", "blog_drafts", ["slug"])
    op.create_index("ix_blog_drafts_status", "blog_drafts", ["status"])
    op.create_index("ix_blog_drafts_created_at", "blog_drafts", ["created_at"])
    op.create_index("ix_blog_drafts_tenant_project", "blog_drafts", ["tenant_id", "project_id"])
    op.create_index("ix_blog_drafts_topic_status", "blog_drafts", ["blog_topic_id", "status"])
    op.create_index("ix_blog_drafts_created", "blog_drafts", ["created_at"], postgresql_using="brin")


def downgrade() -> None:
    op.drop_index("ix_blog_drafts_created", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_topic_status", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_tenant_project", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_created_at", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_status", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_slug", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_blog_topic_id", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_project_id", table_name="blog_drafts")
    op.drop_index("ix_blog_drafts_tenant_id", table_name="blog_drafts")
    op.drop_table("blog_drafts")

    op.drop_index("ix_blog_topics_dedupe", table_name="blog_topics")
    op.drop_index("ix_blog_topics_priority", table_name="blog_topics")
    op.drop_index("ix_blog_topics_tenant_project", table_name="blog_topics")
    op.drop_index("ix_blog_topics_plan_status", table_name="blog_topics")
    op.drop_index("ix_blog_topics_created_at", table_name="blog_topics")
    op.drop_index("ix_blog_topics_status", table_name="blog_topics")
    op.drop_index("ix_blog_topics_target_landing_page_id", table_name="blog_topics")
    op.drop_index("ix_blog_topics_search_intent", table_name="blog_topics")
    op.drop_index("ix_blog_topics_target_keyword", table_name="blog_topics")
    op.drop_index("ix_blog_topics_blog_plan_id", table_name="blog_topics")
    op.drop_index("ix_blog_topics_project_id", table_name="blog_topics")
    op.drop_index("ix_blog_topics_tenant_id", table_name="blog_topics")
    op.drop_table("blog_topics")

    op.drop_index("ix_blog_plans_created", table_name="blog_plans")
    op.drop_index("ix_blog_plans_tenant_project", table_name="blog_plans")
    op.drop_index("ix_blog_plans_created_at", table_name="blog_plans")
    op.drop_index("ix_blog_plans_status", table_name="blog_plans")
    op.drop_index("ix_blog_plans_project_id", table_name="blog_plans")
    op.drop_index("ix_blog_plans_tenant_id", table_name="blog_plans")
    op.drop_table("blog_plans")

    draft_status.drop(op.get_bind(), checkfirst=True)
    topic_status.drop(op.get_bind(), checkfirst=True)
    search_intent.drop(op.get_bind(), checkfirst=True)
    plan_status.drop(op.get_bind(), checkfirst=True)
