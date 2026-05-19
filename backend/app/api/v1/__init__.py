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
    geo_aeo,
    knowledge,
    blogs,
    search_console,
    repos,
    planner,
    serp,
    visibility,
    agents,
    billing,
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
api_router.include_router(geo_aeo.router, prefix="/geo-aeo", tags=["GEO/AEO"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge Base"])
api_router.include_router(blogs.router, prefix="/blogs", tags=["Blogs"])
api_router.include_router(search_console.router, prefix="/search-console", tags=["Search Console"])
api_router.include_router(repos.router, prefix="/repos", tags=["SEO Code Agent"])
api_router.include_router(planner.router, prefix="/planner", tags=["Weekly SEO Planner"])
api_router.include_router(serp.router, prefix="/serp", tags=["SERP Analysis"])
api_router.include_router(visibility.router, prefix="/visibility", tags=["AI Visibility"])
api_router.include_router(agents.router, prefix="/agents", tags=["AI Agents"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
