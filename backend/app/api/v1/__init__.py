"""
SEO Agent SaaS - API v1 Router
"""
from fastapi import APIRouter

from app.api.v1.routes import (
    auth,
    users,
    projects,
    crawl,
    audit,
    semantic,
    internal_links,
    llm,
    content_optimization,
    copy_review,
    geo_aeo,
    knowledge,
    blogs,
    blog_publishing,
    impact,
    search_console,
    sitemaps,
    robots,
    verification,
    deployments,
    briefing,
    site_validation,
    mission_control,
    telemetry,
    queue,
    index_queue,
    fingerprint,
    framework_patches,
    pagespeed,
    indexing,
    keyword_baselines,
    rank_tracking,
    repos,
    planner,
    schedules,
    seo_runs,
    serp_snapshots,
    serp,
    visibility,
    agents,
    billing,
    brain,
)

# Create API router
api_router = APIRouter()

# Include route modules
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(crawl.router, prefix="/crawls", tags=["Crawls"])
api_router.include_router(crawl.router, prefix="/crawl", tags=["Crawling"])
api_router.include_router(audit.router, prefix="/audits", tags=["SEO Audits"])
api_router.include_router(semantic.router, prefix="/semantic", tags=["Semantic SEO"])
api_router.include_router(internal_links.router, prefix="/internal-links", tags=["Internal Links"])
api_router.include_router(llm.router, prefix="/llm", tags=["Local LLM"])
api_router.include_router(content_optimization.router, prefix="/content-optimization", tags=["Content Optimization"])
api_router.include_router(copy_review.router, prefix="/copy-review", tags=["SEO Copy Review"])
api_router.include_router(geo_aeo.router, prefix="/geo-aeo", tags=["GEO/AEO"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge Base"])
api_router.include_router(blogs.router, prefix="/blogs", tags=["Blogs"])
api_router.include_router(blog_publishing.router, prefix="/blog-publishing", tags=["Blog Publishing"])
api_router.include_router(search_console.router, prefix="/search-console", tags=["Search Console"])
api_router.include_router(sitemaps.router, prefix="/search-console", tags=["Sitemap Intelligence"])
api_router.include_router(robots.router, prefix="/robots", tags=["Robots.txt Intelligence"])
api_router.include_router(verification.router, prefix="/verification", tags=["After-Merge Verification"])
api_router.include_router(deployments.router, prefix="/deployments", tags=["Deployment Intelligence"])
api_router.include_router(briefing.router, prefix="/briefing", tags=["Daily Executive Briefing"])
api_router.include_router(site_validation.router, prefix="/site-validation", tags=["Live Site Validation"])
api_router.include_router(mission_control.router, prefix="/mission-control", tags=["Mission Control"])
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["Scheduler Telemetry"])
api_router.include_router(queue.router, prefix="/queue", tags=["Durable Queue"])
api_router.include_router(index_queue.router, prefix="/index-queue", tags=["Auto Index Queue"])
api_router.include_router(fingerprint.router, prefix="/fingerprint", tags=["Technology Fingerprint"])
api_router.include_router(framework_patches.router, prefix="/framework-patches", tags=["Framework Patch Generator"])
api_router.include_router(pagespeed.router, prefix="/pagespeed", tags=["Core Web Vitals"])
api_router.include_router(brain.router, prefix="/brain", tags=["SEO Brain (Orchestrator)"])
api_router.include_router(indexing.router, prefix="/indexing", tags=["GSC Indexing Intelligence"])
api_router.include_router(keyword_baselines.router, tags=["Manual Keyword Baselines"])
api_router.include_router(rank_tracking.router, prefix="/rank-tracking", tags=["Rank Tracking"])
api_router.include_router(impact.router, prefix="/impact", tags=["SEO Impact Tracking"])
api_router.include_router(repos.router, prefix="/repos", tags=["SEO Code Agent"])
api_router.include_router(planner.router, prefix="/planner", tags=["Weekly SEO Planner"])
api_router.include_router(schedules.router, prefix="/schedules", tags=["SEO Scheduler"])
api_router.include_router(schedules.internal_scheduler_router, prefix="/scheduler", tags=["SEO Scheduler"])
api_router.include_router(schedules.scheduled_runs_router, prefix="/scheduled-runs", tags=["SEO Scheduler"])
api_router.include_router(seo_runs.router, tags=["One-click SEO Runs"])
api_router.include_router(serp.router, prefix="/serp", tags=["SERP Analysis"])
api_router.include_router(serp_snapshots.router, prefix="/serp-snapshots", tags=["Manual SERP Snapshots"])
api_router.include_router(visibility.router, prefix="/visibility", tags=["AI Visibility"])
api_router.include_router(agents.router, prefix="/agents", tags=["AI Agents"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
