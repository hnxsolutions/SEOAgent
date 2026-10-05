# Azure deployment readiness

**Verdict: NOT READY — six blockers, all fixable in a day.**

Assessed 2026-10-05 against the running Docker stack on the development machine.
The application itself is production-shaped: it runs, it migrates itself, it
restarts cleanly, and the autonomous loop works unattended. What is not ready is
the **deployment configuration**, which is still a development compose file
wearing a production label.

Target architecture assumed: a single Azure VM running Docker Compose, with
Postgres, Redis, Qdrant and Ollama as containers or on-host services. No managed
Azure services are required, and nothing below introduces a paid dependency.

---

## Blockers

### 1. The backend runs with `--reload` (critical)

`docker-compose.yml` starts the API as:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`--reload` runs a file-watching supervisor, holds extra file descriptors, and
restarts the process on any write into the image. It is a development
convenience and must not be what serves traffic.

**Fix:** drop `--reload` and run multiple workers in the production override:
`uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`.

### 2. Source is bind-mounted over the image on five services (critical)

```
volumes:
  - ./backend:/app
```

appears on `backend`, `worker`, `scheduler`, `crawl-worker` and one more. This
means the running code is whatever is in the working directory on the VM, not
what was built and tested into the image. A half-finished `git pull` becomes a
half-deployed application.

**Fix:** remove the bind mounts in the production override so the image is the
unit of deployment.

### 3. Postgres, Redis and Qdrant are published to the host (critical)

The compose file publishes `5432`, `6379`, `6333` and `6334`. On an Azure VM
these bind to `0.0.0.0` and are reachable from the internet unless the Network
Security Group happens to block them — security that lives outside the artefact
and is one portal click from being wrong.

Postgres currently has a default password of `seoagent_password`.

**Fix:** stop publishing them, or bind to loopback (`127.0.0.1:5432:5432`).
Only `80`/`443` should be open. Set a real `POSTGRES_PASSWORD`.

### 4. There is no Ollama service and no model volume (critical for content)

Ollama is not in `docker-compose.yml` at all; the stack reaches it on the host
via `host.docker.internal`. On the development machine that works because Ollama
Desktop is installed. **A fresh Azure VM has no Ollama and no model**, so every
content feature would be gated from the first boot.

`qwen2.5:3b` is ~1.9 GB and must persist across container restarts, or every
deploy re-downloads it.

**Fix:** either install Ollama on the VM as a systemd service and keep
`host.docker.internal` (the `extra_hosts: host.docker.internal:host-gateway`
mapping added in this phase already makes that work on Linux), or add an
`ollama` service with a named volume on `/root/.ollama` and a one-shot
`ollama pull qwen2.5:3b` init step. Either way the model directory must be a
persistent volume.

### 5. No TLS, and `nginx` is behind a profile

The `nginx` service exists but carries `profiles: [production]`, so
`docker compose up -d` does not start it. There is no certificate story.
Google Search Console OAuth and GitHub callbacks both require HTTPS redirect
URIs in production.

**Fix:** start nginx in the production override, terminate TLS there (Let's
Encrypt via certbot is free), and update `GOOGLE_OAUTH_REDIRECT_URI`,
`GITHUB_CALLBACK_URL`, `APP_URL`, `FRONTEND_URL` and `CORS_ORIGINS` to the real
HTTPS host.

### 6. No resource limits, on a box that runs a language model

Nothing declares `deploy.resources.limits`. `qwen2.5:3b` on CPU took **99
seconds** for one article generation and will occupy a core for that whole time.
The crawler, four Python services, Postgres, Redis and Qdrant share the same VM.
Without limits, a crawl of a large site and a drafting slot firing together can
starve Postgres and take the API down with it.

**Fix:** set memory and CPU limits per service, and size the VM for the model.

---

## Ready as-is

| Area | State |
|---|---|
| Migrations | `alembic upgrade head` runs on backend start; verified to 0045, single head |
| Restart behaviour | `restart: unless-stopped` on all 8 services; schedules survived a restart (12 before, 12 after) |
| Health checks | 7 of 8 services declare one |
| Data persistence | Named volumes for `postgres_data`, `redis_data`, `qdrant_data` |
| Secrets | No literal secrets in `docker-compose.yml`; all `${VAR}` references |
| Scheduler | Starts by default, survives a failed tick, idempotent provisioning |
| Free-only | No paid API anywhere; GSC, PageSpeed and Ollama are the only externals |
| Logging | Structured (`structlog`) to stdout, which is what a container should do |

---

## Sizing

Minimum for the full stack **including** a local model:

- **8 vCPU / 16 GB RAM** (Standard_D8s_v5 or similar). A 3B model on CPU is the
  constraint; 4 vCPU works but a drafting slot will saturate it.
- **128 GB** premium SSD — Postgres, Qdrant vectors, crawl data and ~2 GB of
  model weights.
- A GPU VM would cut generation from ~99s to a few seconds, but is not required
  and costs considerably more.

---

## Before the first deploy

1. Add `docker-compose.prod.yml` overriding: no `--reload`, no bind mounts, no
   published database ports, nginx on, resource limits.
2. Provision Ollama and pre-pull `qwen2.5:3b` onto a persistent volume.
3. Generate real values for `AUTH_SECRET`, `GSC_TOKEN_ENCRYPTION_KEY`,
   `POSTGRES_PASSWORD`, `SCHEDULER_INTERNAL_API_KEY`.
4. Point the OAuth redirect URIs at the HTTPS host and re-consent Google.
5. Set `APP_ENV=production`, `APP_DEBUG=false`, `LOG_LEVEL=INFO`.
6. Decide `SCHEDULER_INTERVAL_SECONDS` for real traffic — 900 is reasonable; it
   is not a load concern since the tick is cheap when nothing is due.
7. Back up `postgres_data`. Nothing else in the stack is irreplaceable.

None of the above requires a paid service beyond the VM itself.
