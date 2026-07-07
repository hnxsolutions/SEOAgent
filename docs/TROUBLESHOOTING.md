# Troubleshooting

Quick fixes for the most common local issues.

## Start / restart the whole stack

```bash
docker compose up -d postgres redis qdrant backend crawl-worker worker frontend
```

- Frontend: http://localhost:3001
- Backend health: http://localhost:8000/health  → should report `"service":"SEO Agent SaaS"`
- API base: http://localhost:8000/api/v1

All long-running services now use `restart: unless-stopped`, so they come back automatically after a Docker Desktop restart or host reboot.

## Frontend port 3001 does not open

Symptom: `curl http://localhost:3001` fails, but you think Docker "shows the frontend running".

1. Check the **actual** state (not just port mappings):
   ```bash
   docker compose ps
   docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
   ```
   A port mapping shown in `docker ps -a` for an **Exited** container does *not* mean it is serving. Look for `Up ... (healthy)`.

2. If the frontend is `Exited (255)` (typical after Docker Desktop restarts), just bring the stack back up:
   ```bash
   docker compose up -d frontend
   ```

3. Verify it serves:
   ```bash
   curl -o /dev/null -w "%{http_code}\n" http://localhost:3001/
   docker compose logs frontend --tail=50
   docker exec seo-agent-frontend sh -c "wget -S -O- http://127.0.0.1:3000 || true"
   ```

4. If you changed frontend code, rebuild the image (it is a compiled Next.js standalone build, not hot-reloaded):
   ```bash
   docker compose build frontend && docker compose up -d frontend
   ```

Notes:
- Host port is `3001` (`FRONTEND_PORT` in `.env`), container port is `3000`.
- The browser calls the API at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000/api/v1`), which is baked in at **build** time. If you change it, rebuild the frontend image.

## "Backend says HNX AI Sales Agent"

That response comes from a **different** project (the Sales Agent stack), not this one. This backend's `/health` returns `"service":"SEO Agent SaaS"`. If you see the Sales Agent name on port 8000, another compose stack is bound to 8000 — stop it, then `docker compose up -d backend`.

## Cannot create / upload a project from the dashboard

1. Confirm the backend is reachable and you are logged in (a valid `access_token` in `localStorage`). A 401 auto-clears the token and redirects to `/login`.
2. The API accepts a bare domain or full URL; the setup form normalizes them:
   `novakoshealthcare.com`, `http://…`, and `https://…` all work.
3. Backend errors now surface verbatim in the setup form (e.g. validation messages), so read the red notice.
4. Reproduce directly against the API:
   ```bash
   # register
   curl -s -X POST http://localhost:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"you@example.com","password":"TestPass123!","full_name":"You"}'
   # login (form-encoded)
   curl -s -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/x-www-form-urlencoded" \
     --data-urlencode "username=you@example.com" --data-urlencode "password=TestPass123!"
   ```
   Use `.com`/`.org` etc. — reserved TLDs like `.local` are rejected by email validation.

## Crawl / SEO run never finishes

1. The one-click SEO run needs the crawl worker:
   ```bash
   docker compose up -d crawl-worker
   docker compose logs crawl-worker --tail=100
   ```
2. Watch a run:
   ```bash
   curl -s http://localhost:8000/api/v1/seo-runs/<RUN_ID>/status -H "Authorization: Bearer <TOKEN>"
   ```
3. The **content** stage uses Ollama. If Ollama is unavailable it is marked `skipped_or_failed` and the run still completes and produces a report — it does not crash the pipeline.

## RQ worker restarts / `No module named rq.__main__`

The `worker` service runs the RQ console script (`rq worker …`), not `python -m rq`. If you see the crash, pull the latest `docker-compose.yml` and `docker compose up -d worker`. This queue (`seo_queue`) is currently idle — the crawl pipeline uses its own worker — so the RQ worker is optional for the local smoke flow.

## Search Console without Google credentials

Expected and safe. With no `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`:
- `/search-console/properties` returns `{"properties":[],"oauth_enabled":false}`.
- Starting OAuth returns `503` with a clear "OAuth is disabled / missing env vars" message.
- Reports show `search_console: "Not connected"` and never fabricate ranking numbers.

To enable the real OAuth path, see [GOOGLE_SEARCH_CONSOLE_OAUTH.md](GOOGLE_SEARCH_CONSOLE_OAUTH.md).
