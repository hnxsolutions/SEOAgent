"""What the agent understands about a website, kept apart from what it was told.

Every other part of this system reads the project brief — `primary_services`,
`industry`, `target_keywords` — and treats it as the truth about the business.
That brief is whatever someone typed into a form, and on most projects it is
blank. This model is the agent's own reading of the site.

**The separation is the point.** Each field records whether it came from the
person who owns the site or from inference, how confident the inference is, and
which pages it was drawn from. A dashboard can then say "Technology company
(inferred, 0.91, from Homepage + About)" instead of presenting a guess as fact,
and `apply_inference` will not let a weak guess overwrite something a human
stated.

Re-inference is gated on `content_hash`: if the pages the profile was built
from have not changed, the profile is reused rather than regenerated. That is
what keeps a 99-second local model call out of every scheduler tick.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class ProfileFieldSource(str, enum.Enum):
    """Where one field's value came from. Never guessed."""

    user = "user"            # stated by the project owner
    inferred = "inferred"    # derived by the agent from the site
    unknown = "unknown"      # neither; the UI shows a gap, not a blank


class WebsiteProfileStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class WebsiteProfile(Base):
    """One living profile per project, versioned on every meaningful change."""

    __tablename__ = "website_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    #: Bumped whenever inference produces a materially different profile, so the
    #: history of what the agent believed is answerable.
    version = Column(Integer, nullable=False, default=1)
    status = Column(
        SQLEnum(WebsiteProfileStatus), nullable=False, default=WebsiteProfileStatus.pending, index=True
    )

    # --- what the agent concluded ------------------------------------------
    business_name = Column(String(255), nullable=True)
    business_type = Column(String(120), nullable=True)
    industry = Column(String(120), nullable=True)
    niche = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    #: Lists, all JSONB because their length is a property of the business.
    services = Column(JSONB, nullable=False, default=list)
    products = Column(JSONB, nullable=False, default=list)
    locations = Column(JSONB, nullable=False, default=list)
    primary_topics = Column(JSONB, nullable=False, default=list)
    brand_terms = Column(JSONB, nullable=False, default=list)
    target_audience = Column(Text, nullable=True)

    #: The pages the profile was read from: [{url, title, role}].
    important_pages = Column(JSONB, nullable=False, default=list)

    # --- provenance ---------------------------------------------------------
    #: field name -> "user" | "inferred" | "unknown".
    field_sources = Column(JSONB, nullable=False, default=dict)
    #: field name -> 0.0-1.0, present only for inferred fields.
    field_confidence = Column(JSONB, nullable=False, default=dict)
    #: field name -> human-readable evidence, e.g. "Homepage + About".
    field_evidence = Column(JSONB, nullable=False, default=dict)

    #: Overall confidence in the inferred half of the profile.
    confidence = Column(Float, nullable=False, default=0.0)
    #: Whether a local model was used, or only deterministic extraction.
    used_llm = Column(String(16), nullable=False, default="no")

    #: Hash of the page content this was built from. Identical hash => reuse.
    content_hash = Column(String(64), nullable=True, index=True)
    error = Column(Text, nullable=True)

    generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # One current profile per project. History lives in `version` plus the
        # snapshot table below, so this stays a single-row lookup on the hot path.
        UniqueConstraint("project_id", name="uq_website_profiles_project"),
        Index("ix_website_profiles_tenant_project", "tenant_id", "project_id"),
    )


class WebsiteProfileSnapshot(Base):
    """A previous version, kept so a changed understanding is auditable."""

    __tablename__ = "website_profile_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("website_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    version = Column(Integer, nullable=False)
    #: The whole profile as it stood, so a diff needs no joins.
    payload = Column(JSONB, nullable=False, default=dict)
    #: What changed against the previous version, in plain words.
    change_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_profile_snapshot_version"),
    )
