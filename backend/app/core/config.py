"""
SEO Agent SaaS - Application Configuration
"""
import json

from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import Any, List, Optional
from functools import lru_cache


#: The shipped placeholder for SECRET_KEY. Named so the production guard can
#: recognise it, and so nothing in the codebase compares against a bare literal.
PLACEHOLDER_SECRET_KEY = "change-this-in-production"


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
    #
    # The default is a placeholder, not a secret, and it is the same string in
    # every copy of this repository — anyone could mint a valid token for a
    # deployment still using it. `_reject_placeholder_secret` below refuses to
    # boot on it in production so it can never ship by accident; development
    # keeps working without configuration.
    SECRET_KEY: str = PLACEHOLDER_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Password reset
    #
    # Short on purpose. A reset link is a bearer credential that takes over an
    # account, and it sits in an inbox that may be shared, forwarded or already
    # compromised — which is the usual reason someone is resetting in the first
    # place. Thirty minutes is enough to read an email and act on it.
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30
    #: Minimum length enforced on a new password at reset time.
    PASSWORD_MIN_LENGTH: int = 8

    # Email delivery over SMTP, using the standard library's smtplib — no extra
    # package, and no third-party sending account required.
    #
    # Five settings, and no switch for encryption: the port decides it. 465 is
    # implicit TLS, everything else (587 for Gmail, 2525 and friends) is
    # STARTTLS. See app/services/email.py — a mode setting is one more thing to
    # get wrong, and the wrong value would mean sending reset links in clear.
    #
    # With SMTP_HOST or SMTP_FROM unset the sender degrades to logging rather
    # than failing, so the password reset flow still works in development.
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    #: The envelope sender. Must be an address the relay will send as — for
    #: Gmail that is the account itself.
    SMTP_FROM: Optional[str] = None
    
    # CORS
    CORS_ORIGINS: Any = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    # Local Ollama connector only; the app must stay self-hosted.
    # Which local model backend serves generation. Only "ollama" ships; the
    # setting exists so a self-hosted alternative can be swapped in without a
    # code change. There is deliberately no paid fallback — if the local model
    # is down, content work waits rather than silently costing money.
    LLM_PROVIDER: str = "ollama"
    # `localhost` is correct only when the backend runs on the same host as
    # Ollama. In Docker it means the container itself, so compose overrides this
    # with host.docker.internal; see the OLLAMA_BASE_URL note in docker-compose.
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
    # Username sent alongside GITHUB_TOKEN when pushing over HTTPS. GitHub
    # ignores the value for a personal access token and requires exactly this
    # one for an app installation token, so it is the safe default for both.
    GITHUB_TOKEN_USERNAME: str = "x-access-token"
    # Authorship for commits the agent makes. Deliberately non-personal: the
    # commit is the agent's, and attributing it to whoever happens to own the
    # token would misrepresent who wrote the change. Supplied per command, so
    # nothing is written to the global git config or to the target repository.
    REPO_AGENT_COMMIT_NAME: str = "SEO Agent"
    REPO_AGENT_COMMIT_EMAIL: str = "seo-agent@localhost"
    # Where pre-apply copies of patched files are kept, so a rollback can undo
    # an apply run. This must be backed by storage that outlives the container:
    # the previous location was beside the checkout, which inside a container
    # meant the writable layer, and recreating the container destroyed the only
    # copy of the rollback material.
    REPO_AGENT_BACKUP_ROOT: str = "/var/lib/seo-agent/backups"
    # End-of-line policy the agent applies to the checkouts it works on,
    # passed per git command. Unset means "whatever git itself resolves",
    # which is the previous behaviour.
    #
    # It needs stating because a container cannot see the host's system git
    # config. On a checkout owned by Windows, the owner's git cleans CRLF back
    # to LF when staging while the container stores it verbatim - so the same
    # file produces two different blobs, and a commit made by the agent
    # rewrites every line of every file it touched. Set it to "true" for a
    # Windows-owned checkout, "input" for a Linux-owned one.
    REPO_AGENT_GIT_AUTOCRLF: Optional[str] = None
    REPO_AGENT_VALIDATION_COMMANDS: str = ""
    REPO_AGENT_GIT_COMMAND_TIMEOUT_SECONDS: int = 120
    # Validation gets its own budget. A typecheck and a production build take
    # minutes, and sharing the 120s git timeout would report every build as a
    # timeout failure - a false "the patch broke the project".
    REPO_AGENT_VALIDATION_TIMEOUT_SECONDS: int = 900
    
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
    # Autonomy: give a new project its recurring cadence (daily GSC + health,
    # weekly audit/scan/linking/performance, monthly strategy, plus drafting
    # slots) the moment it is created. Idempotent; see schedule_provisioning.
    AUTO_PROVISION_SCHEDULES_ON_PROJECT_CREATE: bool = True
    # Articles drafted per week by default. Each one is its own weekly schedule
    # on a different weekday, so the cadence is visible as rows, not as a count.
    DEFAULT_BLOGS_PER_WEEK: int = 2
    # Pages the recurring/one-click SEO run crawls. The crawler itself supports
    # up to 10,000; this is the default working set, not a hard ceiling.
    #
    # 100 was too small to be honest about. A site whose sitemap lists 110 URLs
    # and whose link graph holds 171 was crawled to 99 and reported as finished,
    # so the audit, the content suggestions and the planner were all built from
    # a little over half the site with nothing saying so. A cap that silently
    # truncates is worse than a slow crawl, because the output looks complete.
    #
    # 1000 covers an ordinary business site end to end. It is still a ceiling
    # rather than a promise: when it does bite, `total_pages_discovered` now
    # reports the real figure so the shortfall is visible instead of hidden.
    SEO_RUN_MAX_PAGES: int = 1000
    # How deep a monthly deep audit goes, when it is worth paying for the time.
    SEO_DEEP_RUN_MAX_PAGES: int = 1000
    # How long an SEO run waits on its crawl. The question asked is whether the
    # crawl is still making progress, not how long it has been running: a fixed
    # wall-clock budget is wrong for a job whose size is a parameter, and the
    # constant that preceded these failed a healthy 99-page crawl at page 78.
    # A crawl that keeps saving pages keeps its budget; one that goes quiet for
    # this long has actually stopped.
    SEO_RUN_CRAWL_STALL_TIMEOUT_SECONDS: int = 240
    # Backstop only, scaled by the page budget, for a site slow enough to
    # deliver one page just inside every stall window. Measured throughput on a
    # real site is ~3.5s/page, so this is roughly three times the honest cost.
    SEO_RUN_CRAWL_SECONDS_PER_PAGE: float = 12.0
    # Floor for that backstop, so a small crawl is not held to a tiny ceiling.
    SEO_RUN_CRAWL_MIN_TIMEOUT_SECONDS: int = 600
    # When a running SEO run is declared abandoned. A live run touches itself
    # every SEO_RUN_HEARTBEAT_SECONDS (30), so silence for this long is not a
    # slow stage — it is a worker that was restarted, killed or lost. Without
    # this the row says "running" forever and the dashboard spins forever.
    SEO_RUN_STALE_AFTER_SECONDS: int = 900
    # Durable background queue (RQ over the existing seo_queue + worker). When
    # enabled, background jobs are enqueued instead of run in-process; the caller
    # falls back to BackgroundTasks if the queue is unavailable.
    QUEUE_ENABLED: bool = True
    QUEUE_JOB_TIMEOUT_SECONDS: int = 1800
    # A full SEO run is a pipeline, not a job: crawl, audit, embed every page,
    # then one local-LLM call per page that needs one. On CPU-only hardware that
    # is hours, and the 30-minute default above was killing it part way through
    # — the work-horse was terminated mid-content and the run was left saying
    # "running" with nobody executing it. Anything enqueueing a full run must
    # pass this instead of relying on the generic default.
    SEO_RUN_JOB_TIMEOUT_SECONDS: int = 14400
    # How many content suggestions are generated at once. Measured on this
    # stack: with Ollama on 4 cores concurrency made throughput *worse*, because
    # one generation already saturates every core. With 8 it helps, and two at a
    # time was the best of the measured options; four was worse again. Raise it
    # only alongside OLLAMA_CPUS, and measure rather than assume.
    CONTENT_LLM_CONCURRENCY: int = 2
    # After a repo-agent PR is merged, wait this long before running the
    # follow-up SEO analysis that verifies whether the fix actually worked.
    VERIFICATION_DELAY_MINUTES: int = 10
    # Deployment intelligence: when a repo-agent PR is merged, track the deploy
    # and only run verification after the site is live. If no deployment signal
    # arrives within this window, verification falls back to the delay above so
    # the loop never stalls. Provider credentials (Vercel/Netlify/etc.) are
    # optional; without them, deploy status arrives via webhook or simulate.
    # Google PageSpeed Insights (Core Web Vitals). The API is official and free;
    # without a key it is heavily rate-limited (HTTP 429). Provide a free key from
    # Google Cloud Console for reliable use.
    GOOGLE_PAGESPEED_API_KEY: Optional[str] = None
    PAGESPEED_API_URL: str = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    # A full Lighthouse run against a heavy page genuinely takes this long:
    # measured 12s for a trivial page, 46s for a content page and 76-85s before
    # the upstream itself gave up. 90 sat just under the real tail, so a desktop
    # analysis that was still working was cut off by our own client.
    PAGESPEED_TIMEOUT_SECONDS: float = 120.0
    DEPLOYMENT_DEFAULT_PROVIDER: str = "custom_webhook"
    DEPLOYMENT_SETTLE_SECONDS: int = 0  # extra wait after deploy success before verifying
    # Deployment provider credentials (all optional; adapters degrade gracefully
    # and never fabricate provider data when a token is missing).
    VERCEL_TOKEN: Optional[str] = None
    VERCEL_PROJECT_ID: Optional[str] = None
    NETLIFY_TOKEN: Optional[str] = None
    NETLIFY_SITE_ID: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    CLOUDFLARE_PAGES_PROJECT: Optional[str] = None
    AWS_AMPLIFY_APP_ID: Optional[str] = None
    AWS_REGION: Optional[str] = None
    FEATURE_CRAWLER_ENABLED: bool = True
    FEATURE_SERP_ANALYSIS_ENABLED: bool = True
    FEATURE_AI_VISIBILITY_ENABLED: bool = True
    FEATURE_COMPETITOR_ANALYSIS_ENABLED: bool = True
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_placeholder_secret(cls, value: str, info) -> str:
        """Refuse to run in production on the shipped placeholder.

        Tokens are signed and verified with this value, so a deployment left on
        the default can have tokens forged by anyone holding this repository.
        Failing at boot is the only safe behaviour — a warning in a log is read
        after the breach, not before it.

        Checked against APP_ENV rather than unconditionally so local development
        and the test suite keep working with no configuration at all.
        """
        environment = str((info.data or {}).get("APP_ENV", "development")).lower()
        if environment == "production" and value == PLACEHOLDER_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the shipped placeholder. Set a real value "
                "in the environment before running in production."
            )
        return value

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
