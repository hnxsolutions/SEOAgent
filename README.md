# SEO Agent SaaS - AI-Powered SEO Platform

A production-grade, multi-tenant SaaS platform for AI-powered SEO analysis and optimization.

## 🚀 Tech Stack

### Frontend
- **Next.js 14** - React framework with App Router
- **TypeScript** - Type-safe development
- **Tailwind CSS** - Utility-first CSS framework
- **Radix UI** - Unstyled, accessible UI components
- **TanStack Query** - Data fetching and caching
- **Zustand** - State management

### Backend
- **FastAPI** - Modern Python web framework
- **SQLAlchemy** - SQL toolkit and ORM
- **PostgreSQL** - Primary database
- **Redis** - Cache and message broker
- **Qdrant** - Vector database for AI embeddings
- **LangGraph** - AI agent orchestration
- **Playwright** - Web crawling and scraping

### Infrastructure
- **Docker & Docker Compose** - Containerization
- **Alembic** - Database migrations
- **Nginx** - Reverse proxy (production)

## 📁 Project Structure

```
seo-agent/
├── backend/                    # FastAPI backend
│   ├── app/
│   │   ├── api/               # API routes
│   │   │   └── v1/
│   │   │       └── routes/    # Route handlers
│   │   ├── core/              # Core configuration
│   │   ├── models/            # Database models
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── services/          # Business logic
│   │   └── main.py            # App entry point
│   ├── alembic/               # Database migrations
│   ├── requirements.txt       # Python dependencies
│   └── Dockerfile
│
├── frontend/                   # Next.js frontend
│   ├── src/
│   │   ├── app/               # App router pages
│   │   ├── components/        # React components
│   │   │   └── ui/            # UI components
│   │   ├── hooks/             # Custom hooks
│   │   ├── lib/               # Utilities and API
│   │   └── stores/            # State management
│   ├── public/                # Static assets
│   ├── package.json
│   └── Dockerfile
│
├── docker-compose.yml         # Docker orchestration
├── .env.example              # Environment variables template
└── README.md
```

## 🛠️ Features

### Core Features
- ✅ **Multi-tenant Architecture** - Isolated workspaces for organizations
- ✅ **Authentication System** - JWT-based auth with refresh tokens
- ✅ **User Management** - Profile management and tenant membership
- ✅ **Project Management** - Create and manage SEO projects

### SEO Features (Foundation)
- ✅ **Web Crawling Engine** - Playwright crawler with Redis workers, robots.txt, sitemap discovery, recursive URL crawling, and SEO extraction
- 🔧 **SERP Analysis** - Search engine results analysis (ready for implementation)
- 🔧 **AI Visibility Tracking** - Track content visibility in AI systems (ready for implementation)
- 🔧 **Competitor Analysis** - Analyze competitor strategies (ready for implementation)

### AI Agent System
- 🔧 **Modular Agent Architecture** - Extensible agent system using LangGraph
- 🔧 **SEO Analyzer Agent** - Automated SEO analysis (ready for implementation)
- 🔧 **Content Optimizer Agent** - AI-powered content optimization (ready for implementation)

### Billing & Subscriptions
- 🔧 **Stripe Integration** - Payment processing (ready for implementation)
- 🔧 **Subscription Management** - Multiple pricing tiers
- 🔧 **Usage Tracking** - Monitor API usage and limits

## 🚀 Getting Started

### Prerequisites

- **Docker** & **Docker Compose** (v2.0+)
- **Node.js** (v18+) for local development
- **Python** (v3.11+) for local development
- **PostgreSQL** (v15+) if running without Docker

### Quick Start with Docker

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd seo-agent
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start all services**
   ```bash
   docker-compose up -d
   ```

4. **Run database migrations**
   ```bash
   docker-compose exec backend alembic upgrade head
   ```

5. **Access the application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs

### Local Development

#### Backend Setup

1. **Create virtual environment**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment**
   ```bash
   cp ../.env.example .env
   # Edit .env with your configuration
   ```

4. **Run migrations**
   ```bash
   alembic upgrade head
   ```

5. **Start development server**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

#### Crawler Engine Setup

The crawler is split between the FastAPI API process and one or more distributed
workers. The API creates crawl jobs in PostgreSQL and enqueues Redis tasks; the
workers use Playwright/Chromium to render pages, respect robots.txt, discover
sitemaps, recursively crawl internal URLs, and persist page SEO data.

**Docker Compose**

```bash
docker compose up postgres redis qdrant backend crawl-worker
```

The backend image installs Playwright Chromium during build. The crawler worker
entrypoint is:

```bash
python -m app.crawler.worker --workers 1 --queue default
```

**Local Windows backend**

```powershell
cd backend
uv pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start a worker in a second terminal after PostgreSQL and Redis are running:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.crawler.worker --workers 1 --queue default
```

Crawler API endpoints:

- `POST /api/v1/crawls/start`
- `GET /api/v1/crawls/{crawl_id}/status`
- `GET /api/v1/crawls/{crawl_id}/results`
- `GET /api/v1/crawls/{crawl_id}/pages`
- `GET /api/v1/crawls/{crawl_id}/errors`
- `POST /api/v1/crawls/{crawl_id}/cancel`

#### Semantic SEO Engine

Semantic indexing is fully self-hosted. It uses `sentence-transformers` with
`BAAI/bge-small-en-v1.5` by default and stores vectors in Qdrant. No OpenAI,
Anthropic, Gemini, SerpAPI, Ahrefs, SEMrush, or other paid API key is required
for semantic indexing.

Run migrations and keep Qdrant available:

```bash
docker compose up postgres redis qdrant backend
docker compose exec backend alembic upgrade head
```

Semantic API endpoints:

- `POST /api/v1/semantic/crawls/{crawl_id}/index`
- `GET /api/v1/semantic/index-runs/{run_id}/status`
- `GET /api/v1/semantic/search?project_id=&query=`
- `GET /api/v1/semantic/pages/{page_id}/similar`
- `GET /api/v1/semantic/crawls/{crawl_id}/clusters`

#### Local Ollama LLM Connector

The local LLM connector uses the official Ollama HTTP API and defaults to
`qwen2.5:3b`. It does not use OpenAI, Anthropic, Gemini, or paid APIs.

Start Ollama locally and verify the model:

```powershell
ollama serve
ollama pull qwen2.5:3b
```

Ollama API endpoints exposed by the backend:

- `GET /api/v1/llm/health`
- `GET /api/v1/llm/models`
- `POST /api/v1/llm/generate`
- `POST /api/v1/llm/chat`

#### Google Search Console API Mode

Search Console monitoring uses the free Google Search Console API through OAuth.
CSV import remains available as a fallback/testing mode, and both sources write
to the same normalized Search Console tables and deterministic opportunity
engine.

Google OAuth is optional. Manual property registration and CSV imports work
without Google credentials. Live automatic GSC syncing requires a Google account
that can access at least one verified Search Console property.

Create Google OAuth credentials:

1. In Google Cloud Console, create or select a project.
2. Enable the **Google Search Console API** for that project.
3. Configure the OAuth consent screen and add your test Google account if the
   app is still in testing mode.
4. Create an OAuth 2.0 **Web application** client.
5. Add this authorized redirect URI for local development:
   `http://localhost:8000/api/v1/search-console/connections/google/callback`
6. Use the read-only Search Console scope:
   `https://www.googleapis.com/auth/webmasters.readonly`

Set these backend environment variables only when you want live GSC syncing:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/search-console/connections/google/callback
```

`SECRET_KEY` must also be set to a strong non-default value. The backend uses it
for JWT signing and to derive the local encryption key for stored Google refresh
tokens.

Then run migrations and connect a property:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

cd ..\frontend
npm run dev
```

From the dashboard, open `/dashboard/setup` or `/dashboard/search-console`, click
**Connect Google Search Console**, complete Google consent, refresh the property
list, select a verified property, then run a manual sync. If OAuth is not
configured, use the manual property + CSV fallback path instead.

Search Console endpoints:

- `POST /api/v1/search-console/connections/google/start`
- `GET /api/v1/search-console/connections/google/callback`
- `GET /api/v1/search-console/properties?refresh=true`
- `POST /api/v1/search-console/projects/{project_id}/property`
- `POST /api/v1/search-console/projects/{project_id}/property/manual`
- `POST /api/v1/search-console/projects/{project_id}/sync`
- `GET /api/v1/search-console/projects/{project_id}/summary`
- `POST /api/v1/search-console/imports` for CSV fallback
- `POST /api/v1/search-console/imports/{import_id}/analyze`
- `GET /api/v1/search-console/imports/{import_id}/opportunities`
- `POST /api/v1/search-console/opportunities/{id}/approve`
- `POST /api/v1/search-console/opportunities/{id}/reject`
- `POST /api/v1/search-console/opportunities/{id}/mark-completed`

#### Production Scheduler / Cron Layer

The scheduler is self-hosted and uses the existing backend modules only. It does
not publish content, apply code patches, create pull requests, merge code, or
deploy sites. It creates analysis runs, recommendations, tasks, and reports for
human review.

Supported schedule types:

- `daily_gsc_sync`
- `weekly_full_seo`
- `weekly_blog_planning`
- `weekly_repo_scan`
- `monthly_deep_audit`

Create a schedule, then run one scheduler tick manually:

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Call the tick endpoint from a cron job, Windows Task Scheduler, or a lightweight
worker process:

```powershell
curl -X POST http://localhost:8000/api/v1/schedules/tick `
  -H "Authorization: Bearer <token>" `
  -H "Content-Type: application/json" `
  -d "50"
```

For Windows Task Scheduler, create a task that runs every 5-15 minutes and calls
the same authenticated `POST /api/v1/schedules/tick` command. For Linux cron,
run the equivalent `curl` command on the same cadence. A tick is idempotent for
active schedules: if a schedule already has a queued/running execution, the
scheduler records a skipped run instead of starting duplicate work.

Scheduler endpoints:

- `POST /api/v1/schedules`
- `GET /api/v1/schedules/projects/{project_id}`
- `GET /api/v1/schedules/{schedule_id}`
- `PATCH /api/v1/schedules/{schedule_id}`
- `POST /api/v1/schedules/{schedule_id}/enable`
- `POST /api/v1/schedules/{schedule_id}/disable`
- `POST /api/v1/schedules/{schedule_id}/run-now`
- `GET /api/v1/schedules/{schedule_id}/runs`
- `GET /api/v1/scheduled-runs/{run_id}/status`
- `POST /api/v1/schedules/tick`

#### SEO Code Agent Foundation

The SEO code agent scans a local website repository, detects SEO implementation
gaps, and creates reviewable patch records. The scan/generate phase does not
auto-commit, push, merge, deploy, or publish. GitHub metadata can be stored, but
local path scanning is the active mode in this foundation phase.

Approved low/medium-risk patches can now be applied to a controlled local git
branch. The apply layer verifies approval status, risk level, original file
hashes, safe repo-root paths, ignored folders, and creates backups before
writing. Optional validation commands can be run before the local commit. Draft
GitHub PR creation is optional and only runs when `GITHUB_TOKEN` plus GitHub repo
metadata are configured; the system never auto-merges or deploys.

Supported first framework: Next.js App Router.

Ignored folders during local scans:

- `node_modules`
- `.next`
- `dist`
- `build`
- `.git`
- `coverage`

Repo code-agent endpoints:

- `POST /api/v1/repos/connections`
- `GET /api/v1/repos/connections`
- `GET /api/v1/repos/connections/{connection_id}`
- `POST /api/v1/repos/connections/{connection_id}/scan`
- `GET /api/v1/repos/scans/{scan_id}/status`
- `GET /api/v1/repos/scans/{scan_id}/files`
- `GET /api/v1/repos/scans/{scan_id}/issues`
- `POST /api/v1/repos/scans/{scan_id}/patches/generate`
- `GET /api/v1/repos/scans/{scan_id}/patches`
- `GET /api/v1/repos/patches/{patch_id}`
- `POST /api/v1/repos/patches/{patch_id}/approve`
- `POST /api/v1/repos/patches/{patch_id}/reject`
- `POST /api/v1/repos/patches/{patch_id}/mark-applied`
- `POST /api/v1/repos/scans/{scan_id}/apply-approved-patches`
- `GET /api/v1/repos/apply-runs/{apply_run_id}/status`
- `GET /api/v1/repos/apply-runs/{apply_run_id}/results`
- `POST /api/v1/repos/apply-runs/{apply_run_id}/create-pr`
- `GET /api/v1/repos/pull-requests/{pr_id}`
- `POST /api/v1/repos/apply-runs/{apply_run_id}/rollback`

Optional local validation commands are disabled by default:

```env
REPO_AGENT_VALIDATION_COMMANDS=npm run lint,npm run typecheck,npm run build
GITHUB_TOKEN=
GITHUB_DEFAULT_BASE_BRANCH=main
```

#### Weekly Autonomous SEO Planner

The weekly planner coordinates existing crawl, audit, semantic, internal link,
content optimization, GEO/AEO, knowledge, blog, Search Console, and repository
signals into a task plan and weekly report. It is deterministic-first and
self-hosted. It does not auto-publish content, auto-merge PRs, auto-deploy, or
apply code patches outside the existing approval workflow.

Planner API endpoints:

- `POST /api/v1/planner/projects/{project_id}/run`
- `GET /api/v1/planner/runs/{run_id}/status`
- `GET /api/v1/planner/projects/{project_id}/runs`
- `GET /api/v1/planner/projects/{project_id}/tasks`
- `GET /api/v1/planner/tasks/{task_id}`
- `POST /api/v1/planner/tasks/{task_id}/approve`
- `POST /api/v1/planner/tasks/{task_id}/reject`
- `POST /api/v1/planner/tasks/{task_id}/mark-in-progress`
- `POST /api/v1/planner/tasks/{task_id}/mark-completed`
- `GET /api/v1/planner/runs/{run_id}/report`
- `GET /api/v1/planner/projects/{project_id}/summary`

#### Frontend Setup

1. **Install dependencies**
   ```bash
   cd frontend
   npm install
   ```

2. **Set up environment**
   ```bash
   cp .env.example .env.local
   # Edit .env.local with your configuration
   ```

3. **Start development server**
   ```bash
   npm run dev
   ```

## 📊 Database Schema

### Core Tables
- **users** - User accounts and authentication
- **tenants** - Organizations/workspaces
- **tenant_members** - User-tenant relationships
- **projects** - SEO projects
- **crawl_jobs** - Web crawling tasks
- **crawl_pages** - Crawled page data
- **semantic_index_runs** - Local embedding/Qdrant indexing jobs
- **semantic_indexed_contents** - Indexed content hashes and Qdrant point IDs
- **gsc_connections** - Encrypted Google Search Console OAuth refresh tokens
- **gsc_properties** - Verified GSC properties selected per project
- **gsc_sync_jobs** - Manual/scheduled GSC API sync job history
- **search_console_imports** - CSV and GSC API import records
- **search_console_rows** - Normalized query/page performance rows
- **search_console_opportunities** - Deterministic SEO opportunities and workflow state
- **repo_connections** - Local/GitHub repository connection metadata
- **repo_scan_runs** - Repository SEO scan execution history
- **repo_files** - Discovered SEO-relevant source files and feature flags
- **seo_code_issues** - Deterministic SEO implementation issues
- **seo_code_patches** - Reviewable SEO-only patch records
- **patch_apply_runs** - Controlled local branch patch-application runs
- **patch_apply_results** - Per-patch apply, skip, conflict, and rollback results
- **pull_request_records** - Optional GitHub draft PR metadata for applied patch runs
- **seo_planner_runs** - Manual/scheduled weekly SEO operating-system runs
- **seo_tasks** - Deduplicated weekly SEO tasks for human approval and execution
- **seo_task_dependencies** - Task dependency and related-work relationships
- **seo_weekly_reports** - Dashboard-ready weekly planner summaries
- **serp_analyses** - SERP analysis jobs
- **serp_results** - SERP analysis results
- **agent_runs** - AI agent execution history

### Vector Collections (Qdrant)
- **seo_semantic_chunks** - Local BGE/E5 semantic SEO vectors

## 🔐 Authentication

The platform uses JWT-based authentication with:
- Access tokens (30 minutes default)
- Refresh tokens (7 days default)
- OAuth2 password flow
- Role-based access control (RBAC)

### API Authentication

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123", "full_name": "John Doe"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user@example.com&password=password123"
```

Registration creates a default workspace for the user, and login tokens include
that tenant ID for tenant-scoped API routes.

## 🔧 Configuration

### Environment Variables

See `.env.example` for all available configuration options:

#### Application
- `APP_NAME` - Application name
- `APP_ENV` - Environment (development/production)
- `SECRET_KEY` - JWT signing key

#### Database
- `POSTGRES_USER` - Database user
- `POSTGRES_PASSWORD` - Database password
- `POSTGRES_DB` - Database name
- `DATABASE_URL` - Full connection string

#### Redis
- `REDIS_URL` - Redis connection URL
- `REDIS_REQUIRED` - Set `true` in production to fail startup if Redis is unavailable; defaults to `false` for local development so queued/background jobs are disabled gracefully.

#### Qdrant
- `QDRANT_URL` - Qdrant vector database URL
- `QDRANT_LOCAL_PATH` - Optional embedded Qdrant storage path for local development without Docker
- `QDRANT_REQUIRED` - Set `true` in production if startup must fail when Qdrant is unavailable; defaults to `false` for local development.

#### Local Semantic Indexing
- `SEMANTIC_EMBEDDING_MODEL` - Local sentence-transformers model
- `SEMANTIC_EMBEDDING_DIMENSION` - Embedding vector dimension
- `SEMANTIC_QDRANT_COLLECTION` - Qdrant collection for semantic vectors
- `SEMANTIC_CHUNK_MAX_WORDS` - Max words per semantic chunk

#### Local Ollama
- `OLLAMA_BASE_URL` - Ollama server URL, default `http://localhost:11434`
- `OLLAMA_DEFAULT_MODEL` - Default local model, default `qwen2.5:3b`
- `OLLAMA_TIMEOUT_SECONDS` - HTTP timeout for local generation requests
- `OLLAMA_MAX_RETRIES` - Retry count for transient local connection failures

#### Google Search Console
- `GOOGLE_CLIENT_ID` - Optional Google OAuth client ID for free GSC API syncing
- `GOOGLE_CLIENT_SECRET` - Optional Google OAuth client secret
- `GOOGLE_REDIRECT_URI` - Backend callback URL for the GSC OAuth flow
- `GSC_SYNC_ROW_LIMIT` - Max rows fetched per sync window
- `GSC_HIGH_IMPRESSIONS_THRESHOLD` - Opportunity threshold for impression-driven rules
- `GSC_POSITION_DROP_THRESHOLD` - Minimum average-position decline for ranking-drop detection
- `GSC_CTR_DROP_THRESHOLD` - Relative CTR decline threshold
- `GSC_CLICK_DECLINE_THRESHOLD` - Relative click decline threshold

#### Stripe (Optional)
- `STRIPE_SECRET_KEY` - Stripe secret key
- `STRIPE_PUBLISHABLE_KEY` - Stripe publishable key

## 📈 API Documentation

Once the backend is running, access the interactive API documentation at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🏗️ Architecture Decisions

### Multi-Tenancy
- Database-level isolation using `tenant_id`
- Row-level security for data access
- Shared infrastructure with logical separation

### Scalability
- Async-first design with FastAPI and asyncpg
- Redis for caching and session management
- Qdrant for efficient vector similarity search
- Background job processing with RQ

### Security
- JWT authentication with refresh tokens
- CORS configuration for cross-origin requests
- Input validation with Pydantic
- SQL injection protection with SQLAlchemy ORM

## 🚧 Roadmap

### Phase 1: Foundation ✅
- [x] Project structure and configuration
- [x] Authentication system
- [x] Multi-tenant architecture
- [x] Database schema
- [x] API foundation

### Phase 2: Core Features (In Progress)
- [ ] Web crawling engine
- [ ] SERP analysis engine
- [ ] AI visibility tracking
- [ ] Competitor analysis

### Phase 3: AI Agents
- [ ] LangGraph integration
- [ ] SEO analyzer agent
- [ ] Content optimizer agent
- [ ] Keyword research agent

### Phase 4: Production Ready
- [ ] Stripe billing integration
- [ ] Advanced analytics
- [ ] Email notifications
- [ ] Performance optimization

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- FastAPI for the excellent web framework
- Next.js team for the amazing React framework
- LangChain/LangGraph for AI agent orchestration
- Qdrant for the vector database
- All open-source contributors

## 📞 Support

For support, please open an issue in the repository or contact the development team.

---

**Note**: This is a foundation architecture. Many features are scaffolded but require implementation of the actual business logic.
