"""
SEO Agent SaaS - Database Models
"""
from app.models.user import User
from app.models.tenant import Tenant
from app.models.project import Project
from app.models.crawl import CrawlJob, CrawlPage
from app.models.audit import SEOAuditRun, SEOIssue, SEOPageScore
from app.models.semantic import SemanticIndexedContent, SemanticIndexRun
from app.models.internal_linking import InternalLinkRecommendation
from app.models.content_optimization import ContentOptimizationRun, ContentOptimizationSuggestion
from app.models.copy_review import SeoCopyPolicy, SeoCopyReview, SeoCopyRevision
from app.models.geo_aeo import GeoAeoPageScore, GeoAeoRecommendation, GeoAeoRun
from app.models.impact import SeoImpactExperiment, SeoImpactResult, SeoImpactSnapshot
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeIndexRun, KnowledgeSource
from app.models.blog import BlogDraft, BlogPlan, BlogTopic
from app.models.blog_publishing import (
    BlogInfrastructureCheck,
    BlogPublishConnection,
    BlogPublishResult,
    BlogPublishRun,
)
from app.models.search_console import (
    GSCConnection,
    GSCProjectMonitorSetting,
    GSCProperty,
    GSCSyncJob,
    SearchConsoleImport,
    SearchConsoleOpportunity,
    SearchConsoleRow,
)
from app.models.indexing import (
    GSCFixValidationResult,
    GSCFixValidationRun,
    GSCIndexingIssue,
    GSCUrlInspectionResult,
    GSCUrlInspectionRun,
)
from app.models.sitemap import GSCSitemapRecord, SitemapIssue
from app.models.robots import RobotsAnalysisRun, RobotsIssue
from app.models.keyword_baseline import KeywordBaseline
from app.models.planner import SeoPlannerRun, SeoTask, SeoTaskDependency, SeoWeeklyReport
from app.models.seo_run import SeoRun
from app.models.scheduler import SeoSchedule, SeoScheduledRun
from app.models.repo_agent import (
    PatchApplyResult,
    PatchApplyRun,
    PullRequestRecord,
    RepoArchitectureProfile,
    RepoConnection,
    RepoFile,
    RepoScanRun,
    SeoCodeIssue,
    SeoCodePatch,
)
from app.models.serp import SERPAnalysis, SERPResult, SerpSnapshot, SerpSnapshotAsset, SerpSnapshotResult
from app.models.agent import AgentRun

__all__ = [
    "User",
    "Tenant",
    "Project",
    "CrawlJob",
    "CrawlPage",
    "SEOAuditRun",
    "SEOIssue",
    "SEOPageScore",
    "SemanticIndexRun",
    "SemanticIndexedContent",
    "InternalLinkRecommendation",
    "ContentOptimizationRun",
    "ContentOptimizationSuggestion",
    "SeoCopyPolicy",
    "SeoCopyReview",
    "SeoCopyRevision",
    "GeoAeoRun",
    "GeoAeoPageScore",
    "GeoAeoRecommendation",
    "SeoImpactExperiment",
    "SeoImpactSnapshot",
    "SeoImpactResult",
    "KnowledgeSource",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "KnowledgeIndexRun",
    "BlogPlan",
    "BlogTopic",
    "BlogDraft",
    "BlogPublishConnection",
    "BlogInfrastructureCheck",
    "BlogPublishRun",
    "BlogPublishResult",
    "SearchConsoleImport",
    "SearchConsoleRow",
    "SearchConsoleOpportunity",
    "GSCConnection",
    "GSCProperty",
    "GSCProjectMonitorSetting",
    "GSCSyncJob",
    "GSCUrlInspectionRun",
    "GSCUrlInspectionResult",
    "GSCIndexingIssue",
    "GSCFixValidationRun",
    "GSCFixValidationResult",
    "GSCSitemapRecord",
    "SitemapIssue",
    "KeywordBaseline",
    "SeoPlannerRun",
    "SeoTask",
    "SeoTaskDependency",
    "SeoWeeklyReport",
    "SeoRun",
    "SeoSchedule",
    "SeoScheduledRun",
    "RepoConnection",
    "RepoArchitectureProfile",
    "RepoScanRun",
    "RepoFile",
    "SeoCodeIssue",
    "SeoCodePatch",
    "PatchApplyRun",
    "PatchApplyResult",
    "PullRequestRecord",
    "SERPAnalysis",
    "SERPResult",
    "SerpSnapshot",
    "SerpSnapshotResult",
    "SerpSnapshotAsset",
    "AgentRun",
]
