"""Initial database schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


subscription_tier = postgresql.ENUM(
    "free", "pro", "enterprise", name="subscriptiontier", create_type=False
)
crawl_status = postgresql.ENUM(
    "pending",
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    name="crawlstatus",
    create_type=False,
)
crawl_priority = postgresql.ENUM(
    "low", "normal", "high", "critical", name="crawlpriority", create_type=False
)
serp_status = postgresql.ENUM(
    "pending", "running", "completed", "failed", name="serpstatus", create_type=False
)
agent_status = postgresql.ENUM(
    "pending", "running", "completed", "failed", name="agentstatus", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    subscription_tier.create(bind, checkfirst=True)
    crawl_status.create(bind, checkfirst=True)
    crawl_priority.create(bind, checkfirst=True)
    serp_status.create(bind, checkfirst=True)
    agent_status.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_tier", subscription_tier, nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "tenant_members",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("status", crawl_status, nullable=True),
        sa.Column("priority", crawl_priority, nullable=True),
        sa.Column("max_pages", sa.Integer(), nullable=True),
        sa.Column("max_depth", sa.Integer(), nullable=True),
        sa.Column("crawl_delay", sa.Float(), nullable=True),
        sa.Column("request_timeout", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("allowed_domains", sa.JSON(), nullable=True),
        sa.Column("excluded_paths", sa.JSON(), nullable=True),
        sa.Column("follow_subdomains", sa.Boolean(), nullable=True),
        sa.Column("rate_limit_requests", sa.Integer(), nullable=True),
        sa.Column("rate_limit_window", sa.Integer(), nullable=True),
        sa.Column("respect_robots_txt", sa.Boolean(), nullable=True),
        sa.Column("sitemap_urls", sa.JSON(), nullable=True),
        sa.Column("render_javascript", sa.Boolean(), nullable=True),
        sa.Column("wait_for_selector", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("total_pages_discovered", sa.Integer(), nullable=True),
        sa.Column("total_pages_crawled", sa.Integer(), nullable=True),
        sa.Column("total_pages_failed", sa.Integer(), nullable=True),
        sa.Column("total_pages_skipped", sa.Integer(), nullable=True),
        sa.Column("total_internal_links", sa.Integer(), nullable=True),
        sa.Column("total_external_links", sa.Integer(), nullable=True),
        sa.Column("total_issues_found", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("queue_name", sa.String(length=100), nullable=True),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_jobs_created", "crawl_jobs", ["created_at"], postgresql_using="brin")
    op.create_index("ix_crawl_jobs_project_id", "crawl_jobs", ["project_id"], unique=False)
    op.create_index("ix_crawl_jobs_status", "crawl_jobs", ["status"], unique=False)
    op.create_index("ix_crawl_jobs_tenant_id", "crawl_jobs", ["tenant_id"], unique=False)
    op.create_index(
        "ix_crawl_jobs_tenant_status", "crawl_jobs", ["tenant_id", "status"], unique=False
    )

    op.create_table(
        "crawl_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=True),
        sa.Column("final_url", sa.String(length=2048), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("content_length", sa.BigInteger(), nullable=True),
        sa.Column("redirect_count", sa.Integer(), nullable=True),
        sa.Column("redirect_chain", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=1000), nullable=True),
        sa.Column("title_length", sa.Integer(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_description_length", sa.Integer(), nullable=True),
        sa.Column("h1", sa.JSON(), nullable=True),
        sa.Column("h2", sa.JSON(), nullable=True),
        sa.Column("h3", sa.JSON(), nullable=True),
        sa.Column("h4", sa.JSON(), nullable=True),
        sa.Column("h5", sa.JSON(), nullable=True),
        sa.Column("h6", sa.JSON(), nullable=True),
        sa.Column("heading_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("internal_links", sa.Integer(), nullable=True),
        sa.Column("external_links", sa.Integer(), nullable=True),
        sa.Column("total_links", sa.Integer(), nullable=True),
        sa.Column("internal_link_urls", sa.JSON(), nullable=True),
        sa.Column("external_link_urls", sa.JSON(), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("canonical_url_normalized", sa.String(length=2048), nullable=True),
        sa.Column("robots_meta", sa.String(length=255), nullable=True),
        sa.Column("noindex", sa.Boolean(), nullable=True),
        sa.Column("nofollow", sa.Boolean(), nullable=True),
        sa.Column("og_title", sa.String(length=1000), nullable=True),
        sa.Column("og_description", sa.Text(), nullable=True),
        sa.Column("og_image", sa.String(length=2048), nullable=True),
        sa.Column("og_type", sa.String(length=100), nullable=True),
        sa.Column("og_url", sa.String(length=2048), nullable=True),
        sa.Column("has_og_tags", sa.Boolean(), nullable=True),
        sa.Column("twitter_card", sa.String(length=100), nullable=True),
        sa.Column("twitter_title", sa.String(length=1000), nullable=True),
        sa.Column("twitter_description", sa.Text(), nullable=True),
        sa.Column("twitter_image", sa.String(length=2048), nullable=True),
        sa.Column("has_twitter_card", sa.Boolean(), nullable=True),
        sa.Column("schema_markup", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schema_types", sa.JSON(), nullable=True),
        sa.Column("has_schema_markup", sa.Boolean(), nullable=True),
        sa.Column("total_images", sa.Integer(), nullable=True),
        sa.Column("images_with_alt", sa.Integer(), nullable=True),
        sa.Column("images_without_alt", sa.Integer(), nullable=True),
        sa.Column("image_alt_texts", sa.JSON(), nullable=True),
        sa.Column("load_time_ms", sa.Float(), nullable=True),
        sa.Column("first_contentful_paint_ms", sa.Float(), nullable=True),
        sa.Column("largest_contentful_paint_ms", sa.Float(), nullable=True),
        sa.Column("time_to_interactive_ms", sa.Float(), nullable=True),
        sa.Column("cumulative_layout_shift", sa.Float(), nullable=True),
        sa.Column("first_input_delay_ms", sa.Float(), nullable=True),
        sa.Column("is_mobile_friendly", sa.Boolean(), nullable=True),
        sa.Column("viewport_meta", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=True),
        sa.Column("hreflang_tags", sa.JSON(), nullable=True),
        sa.Column("issues", sa.JSON(), nullable=True),
        sa.Column("issue_count", sa.Integer(), nullable=True),
        sa.Column("critical_issues", sa.Integer(), nullable=True),
        sa.Column("warning_issues", sa.Integer(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("crawl_order", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("crawled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_pages_content_hash", "crawl_pages", ["content_hash"], unique=False)
    op.create_index("ix_crawl_pages_crawl_job_id", "crawl_pages", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_pages_crawled", "crawl_pages", ["crawled_at"], postgresql_using="brin")
    op.create_index("ix_crawl_pages_normalized_url", "crawl_pages", ["normalized_url"], unique=False)
    op.create_index("ix_crawl_pages_status", "crawl_pages", ["status_code"], unique=False)
    op.create_index("ix_crawl_pages_url", "crawl_pages", ["url"], unique=False)
    op.create_index("ix_crawl_pages_url_crawl", "crawl_pages", ["url", "crawl_job_id"], unique=False)

    op.create_table(
        "crawl_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=True),
        sa.Column("link_text", sa.String(length=500), nullable=True),
        sa.Column("link_type", sa.String(length=20), nullable=True),
        sa.Column("rel_attribute", sa.String(length=255), nullable=True),
        sa.Column("is_nofollow", sa.Boolean(), nullable=True),
        sa.Column("is_sponsored", sa.Boolean(), nullable=True),
        sa.Column("is_ugc", sa.Boolean(), nullable=True),
        sa.Column("target_attribute", sa.String(length=50), nullable=True),
        sa.Column("surrounding_text", sa.Text(), nullable=True),
        sa.Column("link_position", sa.String(length=50), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("is_broken", sa.Boolean(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["source_page_id"], ["crawl_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_links_crawl_job_id", "crawl_links", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_links_source_page_id", "crawl_links", ["source_page_id"], unique=False)
    op.create_index("ix_crawl_links_type_status", "crawl_links", ["link_type", "is_broken"], unique=False)
    op.create_index("ix_crawl_links_url", "crawl_links", ["url"], unique=False)

    op.create_table(
        "crawl_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error_type", sa.String(length=100), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["crawl_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_errors_created_at", "crawl_errors", ["created_at"], unique=False)
    op.create_index("ix_crawl_errors_crawl_job_id", "crawl_errors", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_errors_error_type", "crawl_errors", ["error_type"], unique=False)
    op.create_index(
        "ix_crawl_errors_type_created", "crawl_errors", ["error_type", "created_at"], unique=False
    )

    op.create_table(
        "crawl_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("module", sa.String(length=100), nullable=True),
        sa.Column("function", sa.String(length=100), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["crawl_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_logs_created", "crawl_logs", ["created_at"], postgresql_using="brin")
    op.create_index("ix_crawl_logs_created_at", "crawl_logs", ["created_at"], unique=False)
    op.create_index("ix_crawl_logs_crawl_job_id", "crawl_logs", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_logs_level", "crawl_logs", ["level"], unique=False)
    op.create_index("ix_crawl_logs_level_created", "crawl_logs", ["level", "created_at"], unique=False)

    op.create_table(
        "robots_txt_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("parsed_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sitemap_urls", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True),
        sa.Column("fetch_error", sa.Text(), nullable=True),
        sa.Column("fetch_attempts", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_robots_txt_cache_domain", "robots_txt_cache", ["domain"], unique=True)

    op.create_table(
        "sitemap_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("parent_sitemap_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sitemap_type", sa.String(length=20), nullable=True),
        sa.Column("urls", sa.JSON(), nullable=True),
        sa.Column("child_sitemaps", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=True),
        sa.Column("fetch_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["parent_sitemap_id"], ["sitemap_cache.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sitemap_cache_url", "sitemap_cache", ["url"], unique=True)

    op.create_table(
        "serp_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("status", serp_status, nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("total_keywords", sa.Integer(), nullable=False),
        sa.Column("analyzed_keywords", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("search_engine", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "serp_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("domain_authority", sa.Integer(), nullable=True),
        sa.Column("page_authority", sa.Integer(), nullable=True),
        sa.Column("backlinks", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["serp_analyses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("status", agent_status, nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("serp_results")
    op.drop_table("serp_analyses")
    op.drop_table("sitemap_cache")
    op.drop_table("robots_txt_cache")
    op.drop_table("crawl_logs")
    op.drop_table("crawl_errors")
    op.drop_table("crawl_links")
    op.drop_table("crawl_pages")
    op.drop_table("crawl_jobs")
    op.drop_table("projects")
    op.drop_table("tenant_members")
    op.drop_table("tenants")
    op.drop_table("users")

    bind = op.get_bind()
    agent_status.drop(bind, checkfirst=True)
    serp_status.drop(bind, checkfirst=True)
    crawl_priority.drop(bind, checkfirst=True)
    crawl_status.drop(bind, checkfirst=True)
    subscription_tier.drop(bind, checkfirst=True)
