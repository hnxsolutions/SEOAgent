# Google Search Console OAuth Setup

This integration uses Google OAuth and the official Search Console API. It does not scrape Google, use paid SERP APIs, or crawl competitor URLs.

## Required Environment Variables

Set these in your local `.env` or production secret manager:

```env
GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/search-console/connections/google/callback
GSC_TOKEN_ENCRYPTION_KEY=change-me-generate-dedicated-token-encryption-seed
FRONTEND_URL=http://localhost:3000
```

For trusted cron calls to the internal scheduler endpoint, also set:

```env
SCHEDULER_INTERNAL_API_KEY=change-me-internal-scheduler-key
```

## Google Cloud Console

1. Open Google Cloud Console and select or create a project.
2. Enable the Google Search Console API for the project.
3. Go to APIs & Services, then Credentials.
4. Create an OAuth client ID with application type `Web application`.
5. Add this local Authorized redirect URI:

```text
http://localhost:8000/api/v1/search-console/connections/google/callback
```

6. Add your production redirect URI when deploying:

```text
https://YOUR_BACKEND_DOMAIN/api/v1/search-console/connections/google/callback
```

## OAuth Consent Screen

1. Configure the OAuth consent screen for your Google Cloud project.
2. Add the app name, support email, and authorized domains for production.
3. Add this scope:

```text
https://www.googleapis.com/auth/webmasters.readonly
```

4. In test mode, add each tester Google account that will connect Search Console.

## Local Test Flow

1. Start the app with Docker Compose.
2. Register or log in.
3. Create a project.
4. Open `/dashboard/search-console`.
5. Click `Connect`.
6. Complete Google OAuth.
7. Confirm the app redirects back to `/dashboard/search-console`.
8. Confirm Search Console properties load.
9. Select the property for the current project.
10. Save the selected property.

## Enable Monitoring

On `/dashboard/search-console`:

1. Select a Search Console property.
2. Enable automatic sync.
3. Choose one cadence:
   - Every day
   - Every 2 days
   - Every 3 days
4. Save monitor settings.

Manual sync can run without enabling the monitor. Scheduled sync requires the monitor to be enabled.

## Scheduler Runner

The backend exposes:

```text
POST /api/v1/scheduler/tick
Header: X-Internal-Api-Key: <SCHEDULER_INTERNAL_API_KEY>
```

The same tick can run from the backend container with:

```bash
python -m app.jobs.scheduler_tick --limit 50
```

Docker Compose includes an optional hourly scheduler service. Start exactly one scheduler runner:

```bash
docker compose --profile scheduler up -d scheduler
```

The base Docker stack does not start this service by default, which avoids duplicate scheduled runners.
