# Atlas Business Intelligence

A Python-first, multi-tenant analytics application with a React interface. Companies upload CSV data, run read-only SQL, build dashboards, generate CSV reports, and manage workspace roles.

## Start locally on Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1
```

Requires Python 3.14 and Node 22. This workspace includes an isolated Python environment and a portable Node download in ignored directories. The script installs dependencies, builds React, and starts FastAPI at **http://127.0.0.1:8000**. Add `-SeedDemo` to explicitly create synthetic data in the configured database. API documentation is at **http://127.0.0.1:8000/docs**.

Local settings load automatically from the ignored root `.env` file for both the API and Celery worker. When `.env` supplies both Neon URLs, the app uses `DATABASE_URL_POOLED`; the direct `DATABASE_URL` remains available for administrative tooling. Explicit process database configuration overrides the local file, so isolated tests never use the local Neon connection. Preserve TLS and channel-binding parameters. No credentials belong in tracked source files.

Restart existing API and worker processes after changing environment settings. Switching from SQLite to Neon does not migrate existing local accounts or datasets. The API initializes its tables on successful startup. If a hostname resolves but PostgreSQL connection attempts time out, check outbound TCP access to port 5432 and the Neon endpoint/network settings. Authentication cannot be verified until a connection completes. A connection timeout applies to each resolved address.

Local demo: **demo@atlas.local** / **AtlasDemo2026!**. Demo seeding is explicit and never runs automatically in production. Create a new account for an empty workspace. The generated sample CSV is at `data/sample-sales.csv`.

For an already prepared checkout:

```powershell
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## Product workflows

1. Create an account and company workspace, or open the local demo.
2. In **Data sources**, upload a UTF-8 CSV. Table and column names are normalized. Limits: 10 MB, 20,000 rows, 50 columns, and 20 datasets per workspace.
3. In **SQL workspace**, select a dataset, run a SELECT query, and save it. Use Ctrl+Enter to run.
4. Create a dashboard and add widgets. Metrics use the first returned value. Bar and line charts use the first column as labels and the second as numeric values. Tables display query results.
5. Generate a report from SQL, check its status in **Reports**, and download the completed CSV.
6. Owners/admins can add existing account holders to the workspace and assign admin, analyst, or viewer access. The workspace switcher supports membership in multiple companies.

Example SQL for the synthetic dataset:

```sql
SELECT month, ROUND(SUM(revenue), 0) AS revenue
FROM sales
GROUP BY month
ORDER BY month;
```

## Architecture

```text
React interface (built with Vite)
            │ same-origin /api requests
            ▼
FastAPI ── authentication + membership + RBAC ── SQLAlchemy
   │                                             │
   │                                             ▼
   │                                  PostgreSQL application records
   │                                  (SQLite for local development)
   ├── tenant-only in-memory SQLite SQL snapshot
   ├── Redis query cache (60 second TTL)
   └── Celery report queue ── worker ── tenant-scoped CSV result
```

The backend is entirely Python. PostgreSQL stores accounts, memberships, datasets, dashboard definitions, saved queries, audit events, and report results. Uploaded records are JSON-backed for this bounded portfolio implementation. SQL runs with SQLite syntax over a tenant-only analytics snapshot, not directly against application tables. This avoids exposing credentials or other companies' records to submitted SQL. It supports joins, aggregations, CTEs, and window functions within the limits below.

Every data endpoint checks membership and scopes object lookup to the authenticated workspace. `X-Tenant-Id` selects a workspace; it never grants membership. JWTs expire after eight hours. Passwords use salted PBKDF2-SHA256 with 600,000 iterations. Cache keys include the tenant, dataset fingerprint, and SQL. CSV exports escape spreadsheet formula prefixes.

| Role | View dashboards/data | Download reports | Upload/run SQL/build | Manage members |
|---|---|---|---|---|
| Owner | Yes | Yes | Yes | Yes |
| Admin | Yes | Yes | Yes | Yes |
| Analyst | Yes | Yes | Yes | No |
| Viewer | Yes | Yes | No | No |

SQL is read-only. An SQLite authorizer blocks writes, attachment, PRAGMAs, schema inspection, and extension/file functions. Execution is limited to three seconds and 1,000 returned rows; CSV reports have the same row limit. The query timeout includes snapshot creation, but the progress handler starts after the snapshot is assembled.

## Full Docker stack

Install Docker with Compose, copy `.env.example` to `.env`, and set fresh `POSTGRES_PASSWORD` and `JWT_SECRET` values. Use an alphanumeric database password for the composed URL, or percent-encode special characters if adapting the configuration.

If `.env` already contains Neon URLs, keep them and add the two Docker settings instead of replacing the file. Compose uses its own internal PostgreSQL URL for the API and worker; the native Python app uses the Neon settings. A missing-secret interpolation error means Compose stopped before creating containers. Validate configuration without printing secrets with `docker compose config --quiet`.

```sh
docker compose up --build -d
docker compose logs -f api worker
```

This runs PostgreSQL 17, Redis 7, FastAPI, React, and a Celery worker. Only the API is bound to localhost; databases are internal. PostgreSQL and Redis have named volumes. Register your first user through the UI. To seed a demo intentionally in a non-production Docker environment:

```sh
docker compose exec api python -m backend.seed
```

## Free deployment: Render + Neon

The included `render.yaml` requests only a **free Render web service**, builds the Dockerfile, generates `JWT_SECRET`, and asks for `DATABASE_URL`. It creates no paid workers or disks. The React build is served by FastAPI, so no separate frontend service is needed.

Deployment requires account access and a source repository:

1. Put this source in a GitHub repository, excluding ignored files and secrets.
2. Create a project on Neon's **Free** plan. Obtain its PostgreSQL connection string with TLS (`sslmode=require`).
3. In Render, create a Blueprint connected to the repository and this `render.yaml`.
4. Enter the Neon **pooled** connection string for `DATABASE_URL` in Render's secret/environment field. Accept only the **Free** service plan. `APP_ENV=production` and `JWT_SECRET` are configured by the blueprint. The local `.env` is excluded from the image and never uploaded.
5. Wait for deployment health to pass, open the returned Render URL, and register your account.

Current verified hosting documentation:

- [Render free service limits](https://render.com/docs/free): free web services sleep after idle periods and have monthly usage limits. Their local filesystem is ephemeral. Free Render PostgreSQL expires after 30 days; this configuration uses Neon instead.
- [Neon Free plan](https://neon.com/blog/neon-free-plan-1-gb-per-project): bounded free PostgreSQL storage and compute; retain the Free plan and stay within its quota.
- [Render Blueprint specification](https://render.com/docs/blueprint-spec).

The free profile intentionally omits a dedicated Redis service and Celery worker. Reports use FastAPI background tasks and save their status/results in PostgreSQL. Pending local jobs are recovered after startup. This profile does not provide a durable distributed task queue or guaranteed uninterrupted execution. The complete Redis/Celery architecture remains available in Docker. Setting `REDIS_URL` switches cache and jobs to Redis/Celery and requires a running worker; do not set it on the single-service free deployment without a worker.

## Checks and verification

```powershell
.\.venv\Scripts\python -m pytest -q
cd frontend
npm.cmd run build
```

Seven API test scenarios exercise tenant isolation, role restrictions, SQL writes/schema/attachment denial, recursive query timeout, dashboard queries, report generation/download isolation, saved-query isolation, CSV validation, formula escaping, authentication, tenant-scoped cache behavior, and result bounds. Tests use temporary SQLite storage and a cache double; they do not claim a live Redis integration check. The React production build and local HTTP health/static responses have been checked.

The local Docker stack has also been verified with live PostgreSQL, a Redis cache hit, and a Celery-generated CSV report. API health reports `postgresql` and `celery`, and the frontend returns HTTP 200. Re-run the integration check from PowerShell with:

```powershell
Get-Content -Raw scripts/smoke-stack.py | docker compose exec -T api python -
```

The check creates and removes its own temporary workspace/report. Hosted deployment remains unverified. Browser visual QA was unavailable because no browser surface was connected.

## Practical scope

This is a working portfolio MVP, not a certified enterprise service. It uses bounded CSV datasets rather than a large-scale warehouse. Schema initialization uses SQLAlchemy `create_all`; add reviewed migrations before evolving a populated deployment. Multi-factor authentication, email verification, password reset, SSO, billing, scheduled reports, PDF exports, S3 ingestion, database-level RLS, backups, and warehouse connectors are not implemented. Viewer access includes dataset previews. Reports and snapshots are materialized in memory, and report contents are stored in the application database. Authentication throttling is shared with Redis in the full stack and per-process without it. Sign-out removes the local token; issued tokens remain valid until expiration.

Keep real customer data out until operational security, quotas, backups, migrations, and monitoring have been reviewed. Never commit credentials or put secret keys into browser code.
