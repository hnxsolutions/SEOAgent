"""Deployment intelligence models.

A Deployment sits between a merged repo-agent PR and after-merge verification: the
system waits for the site to actually deploy before it re-measures SEO, so the
before/after comparison reflects the live site rather than an undeployed change.
Reuses FKs to projects and pull requests — no data duplicated.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class DeploymentProvider(str, enum.Enum):
    vercel = "vercel"
    netlify = "netlify"
    cloudflare_pages = "cloudflare_pages"
    aws_amplify = "aws_amplify"
    docker = "docker"
    github_pages = "github_pages"
    custom_webhook = "custom_webhook"
    unknown = "unknown"


class DeploymentStatus(str, enum.Enum):
    pending = "pending"     # merged, waiting for the deploy to start/finish
    building = "building"
    success = "success"
    failed = "failed"
    skipped = "skipped"     # no deployment tracking configured


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    pull_request_id = Column(UUID(as_uuid=True), ForeignKey("pull_request_records.id"), nullable=True, index=True)

    provider = Column(SQLEnum(DeploymentProvider), default=DeploymentProvider.unknown, nullable=False, index=True)
    status = Column(SQLEnum(DeploymentStatus), default=DeploymentStatus.pending, nullable=False, index=True)
    commit_sha = Column(String(128), nullable=True, index=True)
    deployment_url = Column(String(2048), nullable=True)
    external_id = Column(String(255), nullable=True, index=True)  # provider's own deployment id

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    logs = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_deployments_project_status", "project_id", "status"),
    )
