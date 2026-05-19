# SEO Agent SaaS - Installation Guide

This guide provides detailed instructions for setting up the SEO Agent SaaS platform in different environments.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Docker Setup (Recommended)](#docker-setup-recommended)
3. [Local Development Setup](#local-development-setup)
4. [Production Deployment](#production-deployment)
5. [Configuration](#configuration)
6. [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Software

- **Docker** (v20.10+) and **Docker Compose** (v2.0+)
- **Git** for version control
- **Node.js** (v18+) for frontend development
- **Python** (v3.11+) for backend development

### Optional Software

- **PostgreSQL** (v15+) if running without Docker
- **Redis** (v7+) if running without Docker
- **VS Code** or your preferred IDE

### System Requirements

- **Minimum**: 4GB RAM, 2 CPU cores, 10GB disk space
- **Recommended**: 8GB RAM, 4 CPU cores, 20GB disk space

## Docker Setup (Recommended)

### 1. Clone the Repository

```bash
git clone <repository-url>
cd seo-agent
```

### 2. Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Generate a secure SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Edit .env file and update:
# - SECRET_KEY (use the generated value)
# - OPENAI_API_KEY (if using OpenAI)
# - Other API keys as needed
nano .env  # or use your preferred editor
```

### 3. Start Services

```bash
# Start all services in detached mode
docker-compose up -d

# View running containers
docker-compose ps

# View logs
docker-compose logs -f
```

### 4. Initialize Database

The backend container runs `alembic upgrade head` on startup. You can also run it
manually after the services are healthy:

```bash
# Run database migrations
docker-compose exec backend alembic upgrade head

# Verify database setup
docker-compose exec postgres psql -U seoagent -d seoagent -c "SELECT * FROM users;"
```

### 5. Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379
- **Qdrant**: http://localhost:6333

### 6. Create First User (Optional)

```bash
# Register a new user via API
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "admin123",
    "full_name": "Admin User"
  }'
```

### Docker Commands Reference

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v

# Rebuild containers
docker-compose build

# Update and restart services
docker-compose pull && docker-compose up -d

# View resource usage
docker stats

# Execute command in container
docker-compose exec backend python -c "print('Hello from backend')"
```

## Local Development Setup

### Backend Setup

#### 1. Set Up Python Environment

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

#### 2. Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt

# Install Playwright browsers (for web crawling)
playwright install
```

#### 3. Configure Environment

```bash
# Copy environment file
cp .env.example .env

# Update database connection to use localhost
# DATABASE_URL=postgresql://seoagent:password@localhost:5432/seoagent
nano .env
```

#### 4. Set Up Database

```bash
# Option 1: Use Docker for database only
docker-compose up -d postgres redis qdrant

# Option 2: Use local PostgreSQL installation
# Create database manually:
# CREATE DATABASE seoagent;
# CREATE USER seoagent WITH PASSWORD 'password';
# GRANT ALL PRIVILEGES ON DATABASE seoagent TO seoagent;

# Run migrations
alembic upgrade head
```

#### 5. Start Development Server

```bash
# Start FastAPI with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or use the make command if available
make run-backend
```

### Frontend Setup

#### 1. Install Dependencies

```bash
cd frontend

# Install npm packages
npm install

# Or use yarn
yarn install
```

#### 2. Configure Environment

```bash
# Copy environment file
cp .env.example .env.local

# Update API URL if needed
# NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
nano .env.local
```

#### 3. Start Development Server

```bash
# Start Next.js development server
npm run dev

# Or use yarn
yarn dev
```

#### 4. Access Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000

## Production Deployment

### Environment Variables for Production

```bash
# Required production settings
APP_ENV=production
APP_DEBUG=False
SECRET_KEY=<strong-random-key>

# Database
DATABASE_URL=postgresql://user:password@production-db:5432/seoagent

# Redis
REDIS_URL=redis://production-redis:6379

# Qdrant
QDRANT_URL=http://production-qdrant:6333

# LLM Provider
OPENAI_API_KEY=<your-openai-key>

# CORS
CORS_ORIGINS=https://yourdomain.com

# Security
RATE_LIMIT_PER_MINUTE=100
```

### Deploy with Docker Compose (Production)

```bash
# Build for production
docker-compose -f docker-compose.yml build

# Start with production profile
docker-compose --profile production up -d

# Run migrations
docker-compose exec backend alembic upgrade head
```

### Deploy with Nginx (Optional)

```bash
# Configure Nginx
sudo cp nginx/nginx.conf /etc/nginx/nginx.conf
sudo cp nginx/conf.d/seo-agent.conf /etc/nginx/conf.d/

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### SSL/HTTPS Setup

```bash
# Using Let's Encrypt
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Auto-renewal
sudo certbot renew --dry-run
```

## Configuration

### Database Configuration

#### PostgreSQL Connection String Format
```
postgresql://username:password@host:port/database
```

#### Example Configurations

**Docker (Internal Network)**:
```
DATABASE_URL=postgresql://seoagent:password@postgres:5432/seoagent
```

**Local Development**:
```
DATABASE_URL=postgresql://seoagent:password@localhost:5432/seoagent
```

**Production**:
```
DATABASE_URL=postgresql://user:password@db.example.com:5432/seoagent
```

### Redis Configuration

#### Redis Connection String Format
```
redis://[:password@]host[:port][/database-number]
```

#### Example Configurations

**Docker**:
```
REDIS_URL=redis://redis:6379/0
```

**Local**:
```
REDIS_URL=redis://localhost:6379/0
```

### LLM Provider Configuration

#### OpenAI
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo-preview
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

#### Anthropic (Claude)
```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-3-opus-20240229
```

#### Google AI
```bash
LLM_PROVIDER=google
GOOGLE_AI_API_KEY=...
GOOGLE_AI_MODEL=gemini-pro
```

### Stripe Configuration

```bash
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_PRO_MONTHLY=price_...
STRIPE_PRICE_ID_PRO_ANNUAL=price_...
```

## Troubleshooting

### Common Issues

#### 1. Port Already in Use

```bash
# Check what's using the port
lsof -i :3000  # Frontend
lsof -i :8000  # Backend
lsof -i :5432  # PostgreSQL

# Kill the process
kill -9 <PID>

# Or change the port in docker-compose.yml
```

#### 2. Database Connection Issues

```bash
# Check if PostgreSQL is running
docker-compose ps postgres

# View PostgreSQL logs
docker-compose logs postgres

# Test connection
docker-compose exec postgres psql -U seoagent -d seoagent
```

#### 3. Migration Errors

```bash
# Reset migrations (WARNING: deletes data)
docker-compose exec backend alembic downgrade base
docker-compose exec backend alembic upgrade head

# Or manually reset database
docker-compose down -v
docker-compose up -d postgres
docker-compose exec backend alembic upgrade head
```

#### 4. Frontend Build Issues

```bash
# Clear Next.js cache
rm -rf .next
rm -rf node_modules
npm install
npm run build
```

#### 5. Python Dependency Issues

```bash
# Clear pip cache
pip cache purge

# Reinstall dependencies
pip install --force-reinstall -r requirements.txt
```

### Debug Mode

#### Backend Debug Mode

```bash
# Set debug mode in .env
APP_DEBUG=True
LOG_LEVEL=DEBUG

# Run with verbose output
docker-compose exec backend uvicorn app.main:app --reload --log-level debug
```

#### Frontend Debug Mode

```bash
# Run with debug output
npm run dev -- --debug

# Check browser console for errors
```

### Performance Monitoring

#### Check Resource Usage

```bash
# Docker resource usage
docker stats

# Database performance
docker-compose exec postgres psql -U seoagent -d seoagent -c "SELECT * FROM pg_stat_database;"

# Redis performance
docker-compose exec redis redis-cli info stats
```

#### Database Optimization

```sql
-- Check slow queries
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Backup and Restore

#### Database Backup

```bash
# Backup PostgreSQL
docker-compose exec postgres pg_dump -U seoagent seoagent > backup.sql

# Restore PostgreSQL
docker-compose exec -T postgres psql -U seoagent seoagent < backup.sql
```

#### Redis Backup

```bash
# Backup Redis
docker-compose exec redis redis-cli SAVE

# Copy RDB file
docker cp seo-agent-redis:/data/dump.rdb ./redis-backup.rdb
```

## Next Steps

After successful installation:

1. **Create your first user** (a default tenant is created automatically)
2. **Configure your LLM provider**
3. **Set up Stripe for billing** (if needed)
4. **Configure email notifications** (if needed)
5. **Deploy to production**

## Support

If you encounter issues not covered in this guide:

1. Check the [GitHub Issues](link-to-issues)
2. Review the [API Documentation](http://localhost:8000/docs)
3. Join our [Community Discord](link-to-discord)
4. Contact support at support@example.com

---

**Note**: This installation guide is for the foundation architecture. Some features may require additional setup as they are implemented.
