"""Models for review-only SEO code repository analysis and patches."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class RepoProvider(str, enum.Enum):
    local = "local"
    github = "github"


class RepoConnectionStatus(str, enum.Enum):
    connected = "connected"
    unavailable = "unavailable"
    failed = "failed"


class RepoScanRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class RepoFilePurpose(str, enum.Enum):
    layout = "layout"
    page = "page"
    sitemap = "sitemap"
    robots = "robots"
    metadata = "metadata"
    jsonld = "jsonld"
    config = "config"
    component = "component"
    unknown = "unknown"


class SeoCodeIssueType(str, enum.Enum):
    missing_metadata = "missing_metadata"
    weak_metadata = "weak_metadata"
    missing_canonical = "missing_canonical"
    missing_open_graph = "missing_open_graph"
    missing_twitter_meta = "missing_twitter_meta"
    missing_schema = "missing_schema"
    missing_sitemap = "missing_sitemap"
    missing_robots = "missing_robots"
    missing_alt_pattern = "missing_alt_pattern"
    heading_semantics_risk = "heading_semantics_risk"
    duplicate_metadata = "duplicate_metadata"
    route_not_in_sitemap = "route_not_in_sitemap"


class SeoCodeIssueSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SeoCodeIssueSource(str, enum.Enum):
    crawl_issue = "crawl_issue"
    content_optimization = "content_optimization"
    geo_aeo = "geo_aeo"
    search_console = "search_console"
    repo_scan = "repo_scan"


class SeoCodeIssueStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    rejected = "rejected"
    fixed = "fixed"


class SeoCodePatchType(str, enum.Enum):
    metadata_update = "metadata_update"
    schema_addition = "schema_addition"
    sitemap_update = "sitemap_update"
    robots_update = "robots_update"
    canonical_addition = "canonical_addition"
    og_twitter_addition = "og_twitter_addition"
    semantic_html_safe_suggestion = "semantic_html_safe_suggestion"


class SeoCodePatchRisk(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SeoCodePatchStatus(str, enum.Enum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


class PatchApplyRunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    rolled_back = "rolled_back"


class PatchValidationStatus(str, enum.Enum):
    not_run = "not_run"
    passed = "passed"
    failed = "failed"


class PatchApplyResultStatus(str, enum.Enum):
    applied = "applied"
    skipped = "skipped"
    failed = "failed"
    rolled_back = "rolled_back"


class PullRequestProvider(str, enum.Enum):
    github = "github"


class PullRequestStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    merged = "merged"
    closed = "closed"
    failed = "failed"


class RepoConnection(Base):
    """A local or GitHub source-code repository connection."""

    __tablename__ = "repo_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    provider = Column(SQLEnum(RepoProvider), nullable=False, index=True)
    repo_url = Column(String(2048), nullable=True)
    local_path = Column(String(2048), nullable=True)
    default_branch = Column(String(255), nullable=True)
    framework = Column(String(255), nullable=True)
    status = Column(SQLEnum(RepoConnectionStatus), default=RepoConnectionStatus.connected, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scans = relationship("RepoScanRun", back_populates="connection", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_repo_connections_tenant_project", "tenant_id", "project_id"),
        Index("ix_repo_connections_created", "created_at", postgresql_using="brin"),
    )


class RepoScanRun(Base):
    """A scan of SEO-relevant files in a repository."""

    __tablename__ = "repo_scan_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=False, index=True)
    status = Column(SQLEnum(RepoScanRunStatus), default=RepoScanRunStatus.queued, nullable=False, index=True)
    framework_detected = Column(String(255), nullable=True)
    files_scanned = Column(Integer, default=0)
    issues_found = Column(Integer, default=0)
    patches_created = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    connection = relationship("RepoConnection", back_populates="scans")
    files = relationship("RepoFile", back_populates="scan_run", cascade="all, delete-orphan")
    issues = relationship("SeoCodeIssue", back_populates="scan_run", cascade="all, delete-orphan")
    patches = relationship("SeoCodePatch", back_populates="scan_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_repo_scan_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_repo_scan_runs_status", "status", "created_at"),
    )


class RepoFile(Base):
    """SEO-relevant repository file discovered during a scan."""

    __tablename__ = "repo_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=False, index=True)
    scan_run_id = Column(UUID(as_uuid=True), ForeignKey("repo_scan_runs.id"), nullable=False, index=True)
    file_path = Column(String(2048), nullable=False, index=True)
    file_type = Column(String(100), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    detected_purpose = Column(SQLEnum(RepoFilePurpose), default=RepoFilePurpose.unknown, nullable=False, index=True)
    has_metadata = Column(Boolean, default=False, nullable=False)
    has_jsonld = Column(Boolean, default=False, nullable=False)
    has_canonical = Column(Boolean, default=False, nullable=False)
    has_open_graph = Column(Boolean, default=False, nullable=False)
    has_twitter_meta = Column(Boolean, default=False, nullable=False)
    has_sitemap = Column(Boolean, default=False, nullable=False)
    has_robots = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    scan_run = relationship("RepoScanRun", back_populates="files")
    issues = relationship("SeoCodeIssue", back_populates="file")

    __table_args__ = (
        Index("ix_repo_files_scan_path", "scan_run_id", "file_path", unique=True),
        Index("ix_repo_files_tenant_project", "tenant_id", "project_id"),
    )


class SeoCodeIssue(Base):
    """A deterministic SEO implementation issue found in repository code."""

    __tablename__ = "seo_code_issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=False, index=True)
    scan_run_id = Column(UUID(as_uuid=True), ForeignKey("repo_scan_runs.id"), nullable=False, index=True)
    file_id = Column(UUID(as_uuid=True), ForeignKey("repo_files.id"), nullable=True, index=True)
    issue_type = Column(SQLEnum(SeoCodeIssueType), nullable=False, index=True)
    severity = Column(SQLEnum(SeoCodeIssueSeverity), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    recommended_fix = Column(Text, nullable=False)
    source_reference_type = Column(SQLEnum(SeoCodeIssueSource), nullable=False, index=True)
    source_reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    status = Column(SQLEnum(SeoCodeIssueStatus), default=SeoCodeIssueStatus.open, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scan_run = relationship("RepoScanRun", back_populates="issues")
    file = relationship("RepoFile", back_populates="issues")
    patches = relationship("SeoCodePatch", back_populates="issue")

    __table_args__ = (
        Index("ix_seo_code_issues_scan_type", "scan_run_id", "issue_type"),
        Index("ix_seo_code_issues_tenant_project", "tenant_id", "project_id"),
    )


class SeoCodePatch(Base):
    """A reviewable SEO-only patch proposal. It is never auto-committed."""

    __tablename__ = "seo_code_patches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=False, index=True)
    scan_run_id = Column(UUID(as_uuid=True), ForeignKey("repo_scan_runs.id"), nullable=False, index=True)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_issues.id"), nullable=False, index=True)
    file_path = Column(String(2048), nullable=False, index=True)
    patch_type = Column(SQLEnum(SeoCodePatchType), nullable=False, index=True)
    original_content_hash = Column(String(64), nullable=False, index=True)
    diff_text = Column(Text, nullable=False)
    proposed_content = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)
    risk_level = Column(SQLEnum(SeoCodePatchRisk), default=SeoCodePatchRisk.low, nullable=False, index=True)
    status = Column(SQLEnum(SeoCodePatchStatus), default=SeoCodePatchStatus.proposed, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scan_run = relationship("RepoScanRun", back_populates="patches")
    issue = relationship("SeoCodeIssue", back_populates="patches")

    __table_args__ = (
        Index("ix_seo_code_patches_scan_status", "scan_run_id", "status"),
        Index("ix_seo_code_patches_tenant_project", "tenant_id", "project_id"),
        Index("ix_seo_code_patches_dedupe", "issue_id", "file_path", "patch_type", "original_content_hash", unique=True),
    )


class PatchApplyRun(Base):
    """A controlled run that applies approved SEO code patches to a local branch."""

    __tablename__ = "patch_apply_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=False, index=True)
    scan_run_id = Column(UUID(as_uuid=True), ForeignKey("repo_scan_runs.id"), nullable=False, index=True)
    branch_name = Column(String(255), nullable=True, index=True)
    status = Column(SQLEnum(PatchApplyRunStatus), default=PatchApplyRunStatus.queued, nullable=False, index=True)
    patches_requested = Column(Integer, default=0)
    patches_applied = Column(Integer, default=0)
    patches_failed = Column(Integer, default=0)
    validation_status = Column(
        SQLEnum(PatchValidationStatus),
        default=PatchValidationStatus.not_run,
        nullable=False,
        index=True,
    )
    validation_output = Column(Text, nullable=True)
    git_diff_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    results = relationship("PatchApplyResult", back_populates="apply_run", cascade="all, delete-orphan")
    pull_requests = relationship("PullRequestRecord", back_populates="apply_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_patch_apply_runs_tenant_project", "tenant_id", "project_id"),
        Index("ix_patch_apply_runs_scan_status", "scan_run_id", "status"),
    )


class PatchApplyResult(Base):
    """Per-patch result from a controlled patch apply run."""

    __tablename__ = "patch_apply_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    apply_run_id = Column(UUID(as_uuid=True), ForeignKey("patch_apply_runs.id"), nullable=False, index=True)
    patch_id = Column(UUID(as_uuid=True), ForeignKey("seo_code_patches.id"), nullable=False, index=True)
    file_path = Column(String(2048), nullable=False, index=True)
    status = Column(SQLEnum(PatchApplyResultStatus), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    original_content_hash = Column(String(64), nullable=True)
    new_content_hash = Column(String(64), nullable=True)
    backup_path = Column(String(2048), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    apply_run = relationship("PatchApplyRun", back_populates="results")

    __table_args__ = (
        Index("ix_patch_apply_results_run_status", "apply_run_id", "status"),
        Index("ix_patch_apply_results_tenant_project", "tenant_id", "project_id"),
    )


class PullRequestRecord(Base):
    """A GitHub draft/open PR created from an approved patch apply run."""

    __tablename__ = "pull_request_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True)
    repo_connection_id = Column(UUID(as_uuid=True), ForeignKey("repo_connections.id"), nullable=False, index=True)
    apply_run_id = Column(UUID(as_uuid=True), ForeignKey("patch_apply_runs.id"), nullable=False, index=True)
    provider = Column(SQLEnum(PullRequestProvider), default=PullRequestProvider.github, nullable=False, index=True)
    branch_name = Column(String(255), nullable=False, index=True)
    base_branch = Column(String(255), nullable=False, index=True)
    commit_sha = Column(String(128), nullable=True)
    pr_number = Column(Integer, nullable=True)
    pr_url = Column(String(2048), nullable=True)
    status = Column(SQLEnum(PullRequestStatus), default=PullRequestStatus.draft, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    apply_run = relationship("PatchApplyRun", back_populates="pull_requests")

    __table_args__ = (
        Index("ix_pull_request_records_tenant_project", "tenant_id", "project_id"),
        Index("ix_pull_request_records_apply_status", "apply_run_id", "status"),
    )
