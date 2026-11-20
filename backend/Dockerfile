# Multi-stage Dockerfile for FastAPI Backend
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
# Retries and a longer socket timeout: this layer pulls a few hundred MB
# including the CPU build of torch, and a single slow read from PyPI was
# enough to fail the whole image build.
RUN pip install --user --no-cache-dir --retries 5 --timeout 120 -r requirements.txt

# Runtime stage
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install runtime dependencies.
# git is required by the Repository AI Agent to create branches, commit patches
# and push pull requests for approved SEO code fixes.
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Ensure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install Chromium and OS libraries required by Playwright crawlers
RUN playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Node.js for the repo agent's validation step.
#
# Before the agent commits a patch it runs the target project's own checks -
# `npx --no-install tsc --noEmit` and `npm run build` - and those need a Node
# runtime here, where the agent runs. Without one a missing interpreter is
# indistinguishable from a failing build.
#
# Copied from the official image rather than installed from Debian, which ships
# a Node too old for current Next.js, or from a vendor setup script, which adds
# an apt repository and pipes a remote script into a shell. This takes the two
# things needed and nothing else, from a pinned tag on the same Debian release
# as this image, so the C library matches.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm     && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx     && node --version && npm --version

ENV PYTHONPATH=/root/.local/lib/python3.11/site-packages
RUN chmod a+x /root

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app

# Mount point for a website checkout the repo agent works on, plus the
# node_modules directory inside it.
#
# Both exist in the image on purpose. Docker initialises an empty named volume
# from the image path it is mounted over, including its ownership, so creating
# node_modules here as appuser is what makes the dependency volume writable by
# the process that has to install into it. Without this the volume comes up
# owned by root and every install fails with EACCES - fixable by hand with a
# chown, but it would need redoing every time the volume is recreated.
RUN mkdir -p /repos/site/node_modules && chown -R appuser:appuser /repos

# Backup root for the repo agent's rollback material, same reasoning: the
# named volume mounted here inherits this ownership, so the non-root user
# the backend runs as can write the pre-apply copies it needs to undo a
# patch. /var/lib is root-owned, so the application cannot create this
# itself at runtime.
RUN mkdir -p /var/lib/seo-agent/backups && chown -R appuser:appuser /var/lib/seo-agent

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
