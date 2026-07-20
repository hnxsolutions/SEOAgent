"""Live site validation model.

Stores the result of validating a live (deployed) URL after a deployment
succeeds: HTTP reachability, HTTPS, robots/sitemap presence, on-page SEO tags,
compression and cache headers. Reuses project + deployment FKs.
"""
from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class SiteValidation(Base):
    __tablename__ = "site_validations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=True, index=True)

    url = Column(String(2048), nullable=False)
    reachable = Column(Boolean, default=False, nullable=False)
    http_status = Column(Integer, nullable=True)
    is_https = Column(Boolean, default=False, nullable=False)

    # {check_name: {"passed": bool, "detail": str}}
    checks = Column(JSONB, nullable=True)
    passed_count = Column(Integer, default=0, nullable=False)
    total_count = Column(Integer, default=0, nullable=False)
    error_message = Column(String(1024), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_site_validations_project_created", "project_id", "created_at"),
    )
