# Azure deployment readiness

**Verdict: READY, with one manual step — issuing a TLS certificate, which needs
a real domain pointed at the VM and therefore cannot be done from a laptop.**

Assessed 2026-10-05 against the running Docker stack; re-assessed after the six
blockers below were fixed.

Target architecture: a single Azure VM running Docker Compose, with Postgres,
Redis, Qdrant, Ollama and nginx as containers. No managed Azure services are
required and nothing here introduces a paid dependency — Let's Encrypt, Ollama
and every datastore are free and self-hosted.

---

## The structural change

`docker-compose.yml` **is now the production file.** The development
conveniences — source bind mounts, `--reload`, published database ports, using
the host's Ollama — live in `docker-compose.override.yml`, which Docker Compose
loads automatically when it sits beside the base file.

```bash
docker compose up -d                        # local: base + override, unchanged
docker compose -f docker-compose.yml up -d  # production: base only
```

This inversion is the point. Previously one file carried `--reload`,
`./backend:/app` and open database ports, and "production" was whatever someone
remembered to change by hand. Now the artefact you deploy is correct when nobody
remembers anything, and the unsafe settings have to be opted into.

An overlay file could not have done this: Compose **merges** volume lists rather
than replacing them, so `volumes: []` in an override does not remove a bind
mount from the base. Verified by experiment before restructuring.

---

## The six blockers, and what fixed them

### 1. `--reload` in the backend command — FIXED

Production now runs `uvicorn ... --workers ${UVICORN_WORKERS:-4}`. The reload
supervisor exists only in the development override.

**Verified:** `--reload` appears 0 times in the production render, once in the
development render.

### 2. Source bind-mounted over the image on five services — FIXED

`./backend:/app` is gone from the base file entirely. The image is the unit of
deployment: what runs is what was built and tested, not whatever is in the
working directory on the VM.

**Verified:** 0 bind mounts of the source tree in the production render.

### 3. Postgres, Redis and Qdrant published to the internet — FIXED

No `ports:` on any datastore in the base file. They are reachable on the compose
network by the services that need them and by nothing else.

`POSTGRES_PASSWORD` no longer has a default. The old `seoagent_password`
fallback meant every deployment that forgot to set it shipped with a known
password; it is now a required variable and Compose refuses to start without it.

**Verified:** the production render publishes exactly two ports — **80 and
443**. The development render still publishes 8000/3000/5432/6379/6333/6334, now
bound to `127.0.0.1` rather than `0.0.0.0`, because a laptop on café Wi-Fi is
exactly where an open database goes wrong.

### 4. No Ollama service and no persistent model volume — FIXED

Added an `ollama` service on a named `ollama_models` volume, plus a one-shot
`ollama-init` that runs `ollama pull` (a no-op once the model is on the volume,
so it is safe on every restart). Without this a fresh VM had neither Ollama nor
a model, and every content feature was gated from first boot.

In development the two services sit behind a `container-ollama` profile, because
a developer already has Ollama on the host with models pulled, and a second
1.9 GB copy serves no purpose.

### 5. No TLS, and nginx behind a profile — FIXED (one manual step remains)

nginx is no longer profile-gated: it starts with the stack and is the only thing
facing the internet. Port 80 serves the ACME challenge, and `certbot-issue` /
`certbot-renew` services are provided under a `tls` profile.

The 443 server block ships as `nginx/conf.d/seo-agent-ssl.conf.disabled`.
nginx refuses to start if a server block references certificates that do not
exist, so shipping it enabled would mean a fresh VM comes up with no web server
at all. Enabling it is a rename, documented in that file.

**This is the one step that cannot be completed from here**: issuing a
certificate requires a real domain with DNS pointed at the VM.

### 6. No resource limits — FIXED

Every service declares `deploy.resources.limits`, all variable-driven so they
can be tuned per VM. Ollama gets the largest share (4 CPU / 8 GB by default)
because generation is the heaviest thing on the box — a measured article took
**99 seconds** on CPU and holds a core throughout. Without limits, a large crawl
and a drafting slot firing together could starve Postgres and take the API down.

**Verified:** 10 services carry limits in the production render.

---

## Verified after the change

| Check | Result |
|---|---|
| Production config parses | valid |
| Production published ports | **80, 443 only** |
| `--reload` in production | 0 occurrences |
| Source bind mounts in production | 0 |
| Resource limits | 10 services |
| nginx profile-gated | no |
| Ollama service + named volume | present |
| **Development stack still works** | 8/8 containers healthy, API 200, Ollama reachable at `host.docker.internal`, model present |

The last row matters most: the restructure must not have cost anything locally,
and it did not. `docker compose up -d` behaves exactly as before.

---

## Sizing

- **8 vCPU / 16 GB RAM** (Standard_D8s_v5 or similar). The 3B model on CPU is
  the constraint; 4 vCPU works but a drafting slot will saturate it.
- **128 GB** premium SSD — Postgres, Qdrant vectors, crawl data, ~2 GB of model
  weights.
- A GPU VM cuts generation from ~99s to seconds but is not required.

---

## Deploying

```bash
# 1. On the VM, with the repo cloned and .env filled in:
cp .env.example .env            # then set real values — see below
docker compose -f docker-compose.yml up -d

# 2. Issue a certificate (needs DNS pointing at this VM, ports 80/443 open):
docker compose -f docker-compose.yml --profile tls run --rm certbot-issue

# 3. Enable TLS:
#    - replace your-domain.example in nginx/conf.d/seo-agent-ssl.conf.disabled
#    - rename it to seo-agent-ssl.conf
#    - uncomment the redirect block in nginx/conf.d/seo-agent.conf
docker compose -f docker-compose.yml restart nginx
docker compose -f docker-compose.yml --profile tls up -d certbot-renew
```

Values that must be set before the first deploy:

- `POSTGRES_PASSWORD` — required, no default
- `AUTH_SECRET`, `GUEST_SESSION_SECRET`, `GSC_TOKEN_ENCRYPTION_KEY`,
  `SCHEDULER_INTERNAL_API_KEY` — generate fresh
- `TLS_DOMAIN`, `TLS_EMAIL`
- `APP_URL`, `FRONTEND_URL`, `CORS_ORIGINS`, `GOOGLE_OAUTH_REDIRECT_URI`,
  `GITHUB_CALLBACK_URL` — the `https://` host. OAuth redirect URIs must match
  exactly and Google will not accept `http://` for a public hostname, so Google
  must be re-consented after the move.
- `APP_ENV=production`, `APP_DEBUG=false`, `LOG_LEVEL=INFO`

Back up `postgres_data`. Nothing else in the stack is irreplaceable — Qdrant
vectors and the Ollama model can both be rebuilt.

---

## Still true, and worth knowing

- **Generation is CPU-bound at ~99 seconds per article.** Functional, slow.
  Only a GPU changes this.
- **The Azure NSG still has to be right.** Nothing in the compose file publishes
  a datastore any more, so a misconfigured NSG no longer exposes the database —
  but 22/80/443 are still the only ports that should be open.
- **No automated backups.** `postgres_data` is a local volume; a VM-level
  snapshot or a `pg_dump` cron is still your responsibility.
