# GSC Real OAuth Smoke Checklist

Use this checklist with real Google OAuth credentials and a verified Search Console property.

- [ ] Set `GOOGLE_CLIENT_ID`.
- [ ] Set `GOOGLE_CLIENT_SECRET`.
- [ ] Set `GOOGLE_OAUTH_REDIRECT_URI` to `http://localhost:8000/api/v1/search-console/connections/google/callback` for local testing.
- [ ] Set `GSC_TOKEN_ENCRYPTION_KEY`.
- [ ] Set `FRONTEND_URL` to `http://localhost:3000`.
- [ ] Start Docker Compose.
- [ ] Register or log in.
- [ ] Create a project.
- [ ] Open `/dashboard/search-console`.
- [ ] Connect Google.
- [ ] Confirm properties load.
- [ ] Select a property for the project.
- [ ] Enable monitor daily.
- [ ] Run manual sync.
- [ ] Confirm Search Console rows are imported.
- [ ] Confirm opportunities are created when the imported data qualifies.
- [ ] Run SEO Analysis.
- [ ] Confirm the report includes the GSC section.
- [ ] Trigger scheduler tick with `python -m app.jobs.scheduler_tick --limit 50` or `POST /api/v1/scheduler/tick`.
- [ ] Confirm the scheduled job runs when due or correctly skips when not due.

Notes:

- This workflow uses the official Google Search Console API only.
- The MVP does not scrape Google search results.
- The MVP does not use paid SERP APIs.
- Competitor URLs remain manually provided context only and are not crawled.
