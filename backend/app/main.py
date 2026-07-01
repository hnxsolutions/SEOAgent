"""
SEO Agent SaaS - Main Application Entry Point
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import structlog

from app.core.config import settings
from app.api.v1 import api_router
from app.core.database import init_db
from app.core.redis import get_redis_status, init_redis
from app.core.qdrant import get_qdrant_status, init_qdrant
from app.services.local_llm import LocalLLMService

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting SEO Agent SaaS backend...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Initialize Redis
    await init_redis()
    logger.info("Redis initialized")
    
    # Initialize Qdrant
    try:
        await init_qdrant()
        logger.info("Qdrant vector database initialized")
    except Exception as exc:
        if settings.QDRANT_REQUIRED:
            raise
        logger.warning("Qdrant is unavailable. Semantic/vector features are disabled in local development.", error=str(exc))
    
    yield
    
    # Shutdown
    logger.info("Shutting down SEO Agent SaaS backend...")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered SEO Agent SaaS Platform",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
    openapi_url="/openapi.json" if settings.APP_ENV == "development" else None,
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security Headers (Production)
if settings.APP_ENV == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # Configure appropriately for production
    )


# Include API routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    ollama = await LocalLLMService().health_check()
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": "1.0.0",
        "environment": settings.APP_ENV,
        "database": {"status": "ok"},
        "redis": get_redis_status(),
        "ollama": {
            "available": bool(ollama.get("available")),
            "default_model": ollama.get("default_model"),
            "default_model_available": bool(ollama.get("default_model_available")),
            "error": ollama.get("error"),
        },
        "qdrant": get_qdrant_status(),
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to SEO Agent SaaS API",
        "docs": "/docs" if settings.APP_ENV == "development" else "Disabled in production"
    }
