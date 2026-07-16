"""
SEO Agent SaaS - Application Configuration
"""
import json

from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import Any, List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )
    
    # Application
    APP_NAME: str = "SEO Agent SaaS"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_URL: str = "http://localhost"
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Database
    POSTGRES_USER: str = "seoagent"
    POSTGRES_PASSWORD: str = "seoagent_password"
    POSTGRES_DB: str = "seoagent"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[str] = None
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_REQUIRED: bool = False
    
    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334
    QDRANT_URL: Optional[str] = None
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_LOCAL_PATH: Optional[str] = None
    QDRANT_REQUIRED: bool = False

    # Local semantic indexing
    SEMANTIC_EMBEDDING_PROVIDER: str = "sentence-transformers"
    SEMANTIC_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    SEMANTIC_EMBEDDING_DIMENSION: int = 384
    SEMANTIC_QDRANT_COLLECTION: str = "seo_semantic_chunks"
    KNOWLEDGE_QDRANT_COLLECTION: str = "seo_knowledge_chunks"
    SEMANTIC_CHUNK_MAX_WORDS: int = 220
    SEMANTIC_CHUNK_OVERLAP_WORDS: int = 40
    SEMANTIC_EMBED_BATCH_SIZE: int = 32
    
    # API
    API_V1_PREFIX: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = "change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # CORS
    CORS_ORIGINS: Any = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    # Local Ollama connector only; the app must stay self-hosted.
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_DEFAULT_MODEL: str = "qwen2.5:3b"
    OLLAMA_TIMEOUT_SECONDS: float = 60.0
    OLLAMA_MAX_RETRIES: int = 2

    # Free Google Search Console API integration. Optional until configured.
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None
    GSC_TOKEN_ENCRYPTION_KEY: Optional[str] = None
    GSC_SYNC_ROW_LIMIT: int = 25000
    GSC_HIGH_IMPRESSIONS_THRESHOLD: int = 100
    GSC_POSITION_DROP_THRESHOLD: float = 2.0
    GSC_CTR_DROP_THRESHOLD: float = 0.25
    GSC_CLICK_DECLINE_THRESHOLD: float = 0.2
    GSC_URL_INSPECTION_MAX_URLS_PER_RUN: int = 50
    GSC_URL_INSPECTION_REQUEST_DELAY_SECONDS: float = 1.0
    GSC_URL_INSPECTION_LANGUAGE_CODE: str = "en-US"
    # Sitemap intelligence
    GSC_SITEMAP_FETCH_TIMEOUT_SECONDS: float = 20.0
    GSC_SITEMAP_MAX_URLS_PARSED: int = 5000
    GSC_SITEMAP_MAX_BYTES: int = 15_000_000
    GSC_SITEMAP_USER_AGENT: str = "SEOAgentBot/1.0 (+sitemap-intelligence)"

    # Optional production scheduler runner protection.
    SCHEDULER_INTERNAL_API_KEY: Optional[str] = None
    SCHEDULER_INTERVAL_SECONDS: int = 3600
    SCHEDULER_TICK_LIMIT: int = 50

    # Optional GitHub PR creation for approved SEO code patches.
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_DEFAULT_BASE_BRANCH: str = "main"
    REPO_AGENT_VALIDATION_COMMANDS: str = ""
    REPO_AGENT_GIT_COMMAND_TIMEOUT_SECONDS: int = 120
    
    # Stripe
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    # Feature Flags
    # Autonomy: when a project is created, immediately kick off the full SEO
    # pipeline (crawl -> audit -> semantic -> content -> planner) in the
    # background so the user does not have to click "Run SEO Analysis".
    AUTO_RUN_SEO_ON_PROJECT_CREATE: bool = True
    # After a repo-agent PR is merged, wait this long before running the
    # follow-up SEO analysis that verifies whether the fix actually worked.
    VERIFICATION_DELAY_MINUTES: int = 10
    # Deployment intelligence: when a repo-agent PR is merged, track the deploy
    # and only run verification after the site is live. If no deployment signal
    # arrives within this window, verification falls back to the delay above so
    # the loop never stalls. Provider credentials (Vercel/Netlify/etc.) are
    # optional; without them, deploy status arrives via webhook or simulate.
    DEPLOYMENT_DEFAULT_PROVIDER: str = "custom_webhook"
    DEPLOYMENT_SETTLE_SECONDS: int = 0  # extra wait after deploy success before verifying
    FEATURE_CRAWLER_ENABLED: bool = True
    FEATURE_SERP_ANALYSIS_ENABLED: bool = True
    FEATURE_AI_VISIBILITY_ENABLED: bool = True
    FEATURE_COMPETITOR_ANALYSIS_ENABLED: bool = True
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        """Allow comma-separated CORS origins in .env files."""
        if isinstance(value, str):
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def get_database_url(self) -> str:
        """Get database URL, using DATABASE_URL if set, otherwise construct it"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @property
    def get_redis_url(self) -> str:
        """Get Redis URL, using REDIS_URL if set, otherwise construct it"""
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    @property
    def get_qdrant_url(self) -> str:
        """Get Qdrant URL, using QDRANT_URL if set, otherwise construct it"""
        if self.QDRANT_URL:
            return self.QDRANT_URL
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def google_oauth_redirect_uri(self) -> Optional[str]:
        """Canonical Google OAuth callback URL with backward-compatible env support."""
        return self.GOOGLE_OAUTH_REDIRECT_URI or self.GOOGLE_REDIRECT_URI


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
