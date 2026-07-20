"""Generated SEO patch models.

A GeneratedSeoPatch is a real, SEO-safe code change the framework-aware generator
produced for a project — driven by the Technology Fingerprint, Framework Strategy,
and Framework Knowledge Base. Unlike the repo-scan patches (which require a
connected repository checkout), these can be generated from the fingerprint alone
so URL-only projects still get executable, framework-native SEO code to apply.

Every patch touches only SEO surfaces (metadata / robots / sitemap / schema /
Open Graph / Twitter) — never UI, business logic, auth, payments, CRM, or the DB.
"""
from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class GeneratedPatchValidation(str, enum.Enum):
    pending = "pending"
    passed = "passed"        # static + safety validation passed
    failed = "failed"        # rejected by validation/safety
    gated = "gated"          # full build/CWV validation needs a connected repo/deploy


class GeneratedSeoPatch(Base):
    __tablename__ = "generated_seo_patches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True)

    framework = Column(String(64), nullable=False, index=True)
    surface = Column(String(32), nullable=False)          # metadata/robots/sitemap/schema/og_twitter
    patch_type = Column(String(48), nullable=False)       # maps to SeoCodePatchType
    target_file = Column(String(512), nullable=False)
    language = Column(String(32), nullable=True)
    generated_code = Column(Text, nullable=False)
    is_new_file = Column(Boolean, default=True)
    code_fixable = Column(Boolean, default=True)          # auto-appliable vs guided setting

    explanation = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    safe = Column(Boolean, default=True, index=True)
    safety_reason = Column(Text, nullable=True)

    validation_status = Column(SQLEnum(GeneratedPatchValidation), default=GeneratedPatchValidation.pending, nullable=False, index=True)
    validation_notes = Column(JSONB, nullable=True)

    seo_before = Column(Integer, nullable=True)
    seo_after = Column(Integer, nullable=True)
    performance_before = Column(Integer, nullable=True)
    performance_after = Column(Integer, nullable=True)

    ready_for_pr = Column(Boolean, default=False, index=True)
    confidence = Column(Integer, nullable=True)
    source_task_id = Column(UUID(as_uuid=True), nullable=True)
    code_hash = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GeneratedSeoPatch {self.framework}/{self.surface} {self.target_file}>"
