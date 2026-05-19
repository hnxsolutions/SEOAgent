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
from app.models.geo_aeo import GeoAeoPageScore, GeoAeoRecommendation, GeoAeoRun
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeIndexRun, KnowledgeSource
from app.models.blog import BlogDraft, BlogPlan, BlogTopic
from app.models.search_console import (
    GSCConnection,
    GSCProperty,
    GSCSyncJob,
    SearchConsoleImport,
    SearchConsoleOpportunity,
    SearchConsoleRow,
)
from app.models.planner import SeoPlannerRun, SeoTask, SeoTaskDependency, SeoWeeklyReport
from app.models.repo_agent import (
    PatchApplyResult,
    PatchApplyRun,
    PullRequestRecord,
    RepoConnection,
    RepoFile,
    RepoScanRun,
    SeoCodeIssue,
    SeoCodePatch,
)
from app.models.serp import SERPAnalysis, SERPResult
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
    "GeoAeoRun",
    "GeoAeoPageScore",
    "GeoAeoRecommendation",
    "KnowledgeSource",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "KnowledgeIndexRun",
    "BlogPlan",
    "BlogTopic",
    "BlogDraft",
    "SearchConsoleImport",
    "SearchConsoleRow",
    "SearchConsoleOpportunity",
    "GSCConnection",
    "GSCProperty",
    "GSCSyncJob",
    "SeoPlannerRun",
    "SeoTask",
    "SeoTaskDependency",
    "SeoWeeklyReport",
    "RepoConnection",
    "RepoScanRun",
    "RepoFile",
    "SeoCodeIssue",
    "SeoCodePatch",
    "PatchApplyRun",
    "PatchApplyResult",
    "PullRequestRecord",
    "SERPAnalysis",
    "SERPResult",
    "AgentRun",
]
