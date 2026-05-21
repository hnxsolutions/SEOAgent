"""Add SEO copy quality and compliance review tables.

Revision ID: 0018_seo_copy_review
Revises: 0017_rank_impact_serp_tracking
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_seo_copy_review"
down_revision: Union[str, None] = "0017_rank_impact_serp_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


copy_source_type = postgresql.ENUM(
    "repo_patch",
    "content_suggestion",
    "blog_draft",
    "faq_suggestion",
    "schema_suggestion",
    "metadata",
    name="seocopysourcetype",
    create_type=False,
)
copy_readiness = postgresql.ENUM(
    "ready",
    "needs_revision",
    "manual_review",
    "rejected",
    name="seocopyapprovalreadiness",
    create_type=False,
)
copy_profile = postgresql.ENUM(
    "default",
    "healthcare",
    "pharma_b2b",
    "finance",
    "legal",
    "ecommerce",
    name="seocopycomplianceprofile",
    create_type=False,
)
revision_status = postgresql.ENUM(
    "pending",
    "accepted",
    "rejected",
    name="seocopyrevisionstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in [copy_source_type, copy_readiness, copy_profile, revision_status]:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "seo_copy_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", copy_source_type, nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_url", sa.String(length=2048), nullable=True),
        sa.Column("target_keyword", sa.String(length=1000), nullable=True),
        sa.Column("original_title", sa.Text(), nullable=True),
        sa.Column("original_description", sa.Text(), nullable=True),
        sa.Column("reviewed_title", sa.Text(), nullable=True),
        sa.Column("reviewed_description", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("compliance_score", sa.Float(), nullable=False),
        sa.Column("approval_readiness", copy_readiness, nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("revision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_seo_copy_reviews_tenant_id": ["tenant_id"],
        "ix_seo_copy_reviews_project_id": ["project_id"],
        "ix_seo_copy_reviews_source_type": ["source_type"],
        "ix_seo_copy_reviews_source_reference_id": ["source_reference_id"],
        "ix_seo_copy_reviews_page_url": ["page_url"],
        "ix_seo_copy_reviews_target_keyword": ["target_keyword"],
        "ix_seo_copy_reviews_approval_readiness": ["approval_readiness"],
        "ix_seo_copy_reviews_created_at": ["created_at"],
        "ix_seo_copy_reviews_tenant_project": ["tenant_id", "project_id"],
        "ix_seo_copy_reviews_source": ["source_type", "source_reference_id"],
        "ix_seo_copy_reviews_readiness": ["approval_readiness", "created_at"],
    }.items():
        op.create_index(name, "seo_copy_reviews", cols)

    op.create_table(
        "seo_copy_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("compliance_profile", copy_profile, nullable=False),
        sa.Column("blocked_phrases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("allowed_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_seo_copy_policies_tenant_id": ["tenant_id"],
        "ix_seo_copy_policies_project_id": ["project_id"],
        "ix_seo_copy_policies_compliance_profile": ["compliance_profile"],
        "ix_seo_copy_policies_created_at": ["created_at"],
        "ix_seo_copy_policies_tenant_project": ["tenant_id", "project_id"],
    }.items():
        op.create_index(name, "seo_copy_policies", cols)

    op.create_table(
        "seo_copy_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", copy_source_type, nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revised_title", sa.Text(), nullable=True),
        sa.Column("revised_description", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("compliance_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", revision_status, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["seo_copy_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, cols in {
        "ix_seo_copy_revisions_tenant_id": ["tenant_id"],
        "ix_seo_copy_revisions_project_id": ["project_id"],
        "ix_seo_copy_revisions_review_id": ["review_id"],
        "ix_seo_copy_revisions_source_type": ["source_type"],
        "ix_seo_copy_revisions_source_reference_id": ["source_reference_id"],
        "ix_seo_copy_revisions_status": ["status"],
        "ix_seo_copy_revisions_created_at": ["created_at"],
        "ix_seo_copy_revisions_tenant_project": ["tenant_id", "project_id"],
        "ix_seo_copy_revisions_source": ["source_type", "source_reference_id"],
    }.items():
        op.create_index(name, "seo_copy_revisions", cols)


def downgrade() -> None:
    op.drop_table("seo_copy_revisions")
    op.drop_table("seo_copy_policies")
    op.drop_table("seo_copy_reviews")
