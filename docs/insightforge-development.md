# InsightForge implementation status

This document tracks the supplied master prompt against the working application.
The prompt attachment ends at `GET /` in section 13; later requirements were not supplied.

## Implemented foundation

- FastAPI modular backend with SQLAlchemy metadata, PostgreSQL deployment and SQLite tests.
- Multiple organizations, JWT login, organization membership checks and owner/admin/analyst/viewer roles.
- Tenant-scoped datasets, saved queries, dashboards, CSV reports and audit events.
- Bounded CSV ingestion: 10 MB, 20,000 rows, 50 columns, 20 datasets per workspace.
- Read-only SQL over an isolated in-memory analytics database, separate from operational PostgreSQL.
- Tenant-aware Redis result cache, dataset fingerprinting and TTL expiration.
- Celery report generation in Docker; local background fallback with restart recovery.
- Editable dashboards with line/bar/table/KPI widgets and shape validation.
- Docker Compose, Render deployment configuration and GitHub Actions.
- InsightForge branding and “Built by Santanu Kumar Adhikari” credit.
- `/api/v1` equivalents of existing endpoints, retaining `/api` compatibility.
- Dataset preview and profiling with authorization checked before reading dataset rows.

## Dataset profiling

`GET /api/v1/datasets/{id}/profile` returns row/column counts, missing cells,
duplicate rows, per-column missing percentages and unique counts. Numeric columns
include min/max/mean/median, interpolated quartiles and Tukey IQR outlier counts.
Columns whose nonempty values are all ISO dates include a date range.

The score is explicitly `100 × cell completeness × row uniqueness`. It describes
completeness and duplication, not business accuracy or schema compliance. Empty
cells mean `null` or an empty string; whitespace is not silently treated as null.
Profiling does not alter the uploaded data. Outliers are observations, not errors.
The preview dialog shows the health summary and column-level statistics.

## Restricted hosted SQL mode

The current engine uses SQLite, not DuckDB. It exposes only the requesting
organization's datasets, uses a runtime authorizer to reject writes, operational
tables, PRAGMA, ATTACH and extension/file functions, and returns at most 1,000
rows. Queries have a three-second progress-handler budget and a value-size limit.
SQL runs against temporary analytics tables, never against operational PostgreSQL.

This is a bounded portfolio mode. It does not provide an OS-enforced worker memory
limit or full process isolation. Do not advertise unrestricted or large-scale SQL
execution. A future DuckDB engine must validate SQLGlot ASTs, use an approved
catalog, disable external access and extensions, and execute in a separately
bounded worker. Parsing alone must never be the security boundary.

## Outstanding master-prompt requirements

| Area | Required work |
| --- | --- |
| Runtime and frontend | Python 3.12 compatibility; TypeScript, Tailwind, React Router, TanStack Query, ECharts migration |
| Authentication | Refresh-token rotation, server-side revocation/logout, invitations, Super Admin, resource-level ACLs |
| Persistence | Alembic migrations, tenant RLS policy design, composite indexes, optimistic concurrency, keyset pagination |
| Ingestion | Object storage, XLSX/JSON/Parquet, chunked ETL, dataset versions, persistent ingestion state machine and idempotency |
| Analytics | Sandboxed DuckDB/SQLGlot, pagination, explain plans, persistent query history, exports and scheduling |
| Metrics | Structured definitions, validated formulas, versions, filters and permissions |
| Dashboards | Additional chart types, axis/filter editor, layout rearrangement, sharing and exports |
| Cache | Metadata/metric caches, stampede protection and hit/miss telemetry |
| Jobs | Persistent job model, retries/backoff, cancellation, crash-safe claiming and short-lived scheduled cloud runner |
| Reports | XLSX/PDF artifacts, templates, recurring schedules and object storage |
| Quality | Reusable domain rules, affected-record exports, schema validation and freshness checks |
| Deployment | Separate Vercel frontend/CORS configuration, Supabase validation and S3-compatible storage configuration |
| Performance | Reproducible measured index/keyset/cache/async benchmarks; no results claimed yet |

## Safe implementation sequence

1. Introduce Alembic and test upgrading a populated database; establish Python 3.12 CI.
2. Add refresh sessions, invitations and explicit dataset/dashboard ACLs with adversarial tenant tests.
3. Add storage adapters and versioned ingestion jobs; validate cancellation, retries and idempotency.
4. Build a separately isolated DuckDB worker and validate malicious SQL plus resource exhaustion.
5. Add structured metrics, query history, scheduling and multi-format reports.
6. Migrate the frontend and extend dashboard interactions against tested API contracts.
7. Measure performance and validate cloud configurations against connected accounts.

The existing Render service name, environment variable names, local database file,
demo credentials and existing tenant identifiers remain compatible. No migration,
cloud deployment or benchmark is implied by the branding change.
