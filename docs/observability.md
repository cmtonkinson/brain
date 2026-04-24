# Observability
This document describes Brain's optional local observability stack: what it
runs, how components connect, and which `.env` values must be set before use.

> Check the [Glossary](glossary.md) for key terms such as _Component_,
> _Substrate_, _Trace_, and _Resource_.

------------------------------------------------------------------------
## Stack
The observability overlay is defined in `docker-compose.observability.yaml` and
is started alongside the base runtime:
```sh
docker compose -f docker-compose.yaml -f docker-compose.observability.yaml up --build
```

The base stack provides the shared `seaweedfs` service. The overlay adds:
- `otel-collector`: receives Brain OTLP over HTTP and forwards traces to
  Langfuse, exposes Brain metrics for Prometheus, and forwards Brain file logs
  to Loki.
- `prometheus`: scrapes the OTel Collector Prometheus exporter for Brain
  metrics.
- `loki`: stores Brain structured logs exported through the OTel Collector.
- `grafana`: UI with Prometheus and Loki datasources provisioned.
- `langfuse-web`: web UI and API at `http://localhost:3000`.
- `langfuse-worker`: background ingestion and processing.
- `clickhouse`: Langfuse event analytics storage.
- `seaweedfs-bucket-init`: creates the `langfuse` bucket.
- `langfuse-postgres-init`: creates the dedicated `langfuse` Postgres user and
  database in the existing `postgres` service.

Brain's existing Postgres, Valkey, and SeaweedFS services are reused. Langfuse
data must stay in its own Postgres database and SeaweedFS bucket/prefixes; it
is operational observability data, not Brain domain state or Object-managed object
data.

------------------------------------------------------------------------
## Storage
All service data is stored in Docker named volumes for performance (avoids
macOS VirtioFS overhead on write-heavy workloads):
- `brain-postgres` — Postgres data (Brain + Langfuse databases)
- `brain-valkey` — Valkey append-only file
- `brain-qdrant` — Qdrant vector storage
- `brain-seaweedfs` — SeaweedFS blob data
- `brain-prometheus` — Prometheus TSDB
- `brain-loki` — Loki chunk storage
- `brain-grafana` — Grafana dashboards and state
- `brain-clickhouse-data` — ClickHouse data
- `brain-clickhouse-logs` — ClickHouse logs

`clickhouse-data-init` prepares the ClickHouse volume directories and sets
ownership to the UID/GID used by the ClickHouse container. Override
`LANGFUSE_CLICKHOUSE_UID` and `LANGFUSE_CLICKHOUSE_GID` only when using a
different ClickHouse image or local ownership model.

------------------------------------------------------------------------
## Connection Map
Local operator endpoints:

| Surface | URL | Notes |
|---|---|---|
| Grafana UI | `http://localhost:3001` | Login with `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`; defaults are `admin` / `replace-me`. |
| Langfuse UI | `http://localhost:3000` | Login with `LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD`. |
| OTel Collector HTTP | `http://localhost:4318` | Brain sends OTLP here when observability is enabled. |
| OTel Collector Prometheus scrape | `http://127.0.0.1:9464/metrics` | Prometheus scrapes Brain public API/Qdrant metrics here. |
| Prometheus UI | `http://127.0.0.1:9090` | Local Prometheus UI for raw metric inspection. |
| Loki API | `http://127.0.0.1:3100` | Local Loki API; Grafana is the intended UI. |
| SeaweedFS S3 API | `http://localhost:8333` | Local S3-compatible endpoint for inspection and smoke tests. |
| ClickHouse HTTP | `http://127.0.0.1:8123` | Bound to localhost by default. |
| ClickHouse native | `127.0.0.1:9000` | Bound to localhost by default. |

Container-to-container endpoints:

| Consumer | Target | Purpose |
|---|---|---|
| `brain-core`, `brain-assistant` | `http://otel-collector:4318` | OTLP trace and metric export. |
| `otel-collector` | `http://langfuse-web:3000/api/public/otel` | Langfuse OTel ingestion. |
| `otel-collector` | `http://loki:3100/otlp` | OTLP log ingestion for Brain structured file logs. |
| `prometheus` | `http://otel-collector:9464/metrics` | Scrape Brain metrics exposed by the collector. |
| `grafana` | `http://prometheus:9090` and `http://loki:3100` | Dashboard datasource access. |
| `langfuse-web`, `langfuse-worker` | `postgres:5432/langfuse` | Dedicated Langfuse Postgres database. |
| `langfuse-web`, `langfuse-worker` | `valkey:6379` | Langfuse queue/cache use. |
| `langfuse-web`, `langfuse-worker` | `http://clickhouse:8123` and `clickhouse:9000` | Langfuse analytics storage and migrations. |
| `langfuse-web`, `langfuse-worker` | `http://seaweedfs:8333` | S3-compatible event/media/export blobs. |

------------------------------------------------------------------------
## Required Secrets
Create or update `.env` at the repository root. Values must be stable across
restarts because Langfuse persists encrypted data and database credentials.

Generate runtime secrets:
```sh
GRAFANA_ADMIN_PASSWORD="$(openssl rand -base64 24)"
LANGFUSE_POSTGRES_PASSWORD="$(openssl rand -hex 32)"
LANGFUSE_DATABASE_URL="postgresql://langfuse:$LANGFUSE_POSTGRES_PASSWORD@postgres:5432/langfuse"
LANGFUSE_CLICKHOUSE_USER=clickhouse
LANGFUSE_CLICKHOUSE_PASSWORD="$(openssl rand -base64 32)"
LANGFUSE_NEXTAUTH_URL=http://localhost:3000
LANGFUSE_NEXTAUTH_SECRET="$(openssl rand -base64 32)"
LANGFUSE_SALT="$(openssl rand -base64 32)"
LANGFUSE_ENCRYPTION_KEY="$(openssl rand -hex 32)"
SEAWEEDFS_S3_ACCESS_KEY_ID="brain-langfuse-$(openssl rand -hex 8)"
SEAWEEDFS_S3_SECRET_ACCESS_KEY="$(openssl rand -base64 32)"
```

`LANGFUSE_POSTGRES_PASSWORD` is embedded in `LANGFUSE_DATABASE_URL`; keep it
URL-safe or percent-encode it before setting the URL. `LANGFUSE_ENCRYPTION_KEY`
must be exactly 64 hex characters. `openssl rand -hex 32` produces the correct
shape.

------------------------------------------------------------------------
## Project Bootstrap
Set Langfuse init values before the first observability boot so the local org,
project, user, and API keys are deterministic:
```sh
LANGFUSE_INIT_ORG_ID=brain
LANGFUSE_INIT_ORG_NAME=Brain
LANGFUSE_INIT_PROJECT_ID=brain-local
LANGFUSE_INIT_PROJECT_NAME=Brain Local
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-$(openssl rand -hex 16)
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-$(openssl rand -hex 32)
LANGFUSE_INIT_USER_EMAIL=you@example.com
LANGFUSE_INIT_USER_NAME=Chris
LANGFUSE_INIT_USER_PASSWORD="$(openssl rand -base64 24)"
```

The OTel Collector authenticates to Langfuse with HTTP Basic auth using the
project public and secret keys:
```sh
LANGFUSE_OTEL_AUTH_HEADER="Basic $(printf '%s:%s' "$LANGFUSE_INIT_PROJECT_PUBLIC_KEY" "$LANGFUSE_INIT_PROJECT_SECRET_KEY" | base64 | tr -d '\n')"
```

If these init values are changed after Langfuse has already created its first
project, update `LANGFUSE_OTEL_AUTH_HEADER` to match the active project keys in
the Langfuse UI or reset the Langfuse database.

------------------------------------------------------------------------
## SeaweedFS Notes
Langfuse requires S3-compatible blob storage. Brain uses SeaweedFS instead of
MinIO for this surface. Langfuse is configured with path-style S3 addressing:
- `LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT=http://seaweedfs:8333`
- `LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE=true`
- `LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT=http://localhost:8333`
- `LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE=true`
- `LANGFUSE_S3_BATCH_EXPORT_ENDPOINT=http://seaweedfs:8333`
- `LANGFUSE_S3_BATCH_EXPORT_FORCE_PATH_STYLE=true`

The base compose stack starts SeaweedFS S3 without credential enforcement. The
SeaweedFS access key and secret are still supplied to Langfuse and bucket-init
containers for S3 client signing. For network exposure beyond local Docker
development, add a SeaweedFS S3 config file and enforce those credentials.

------------------------------------------------------------------------
## Startup Checks
After `.env` is set, validate the compose shape:
```sh
docker compose -f docker-compose.yaml -f docker-compose.observability.yaml config --quiet
```

Then start the stack:
```sh
docker compose -f docker-compose.yaml -f docker-compose.observability.yaml up --build
```

Expected first-boot behavior:
- `langfuse-postgres-init` exits successfully after creating the `langfuse`
  role/database if missing.
- `clickhouse-data-init` exits successfully after creating and owning the
  ClickHouse volume directories.
- `seaweedfs-bucket-init` exits successfully after creating the `langfuse`
  bucket if missing.
- `brain-core` and `brain-assistant` set observability enabled via compose
  environment overrides and write structured file logs under `./logs/` for
  collector ingestion.
- The Grafana UI is reachable at `http://localhost:3001` with Prometheus and
  Loki datasources provisioned.
- The Langfuse UI is reachable at `http://localhost:3000`.

To verify trace flow, send one Brain turn through the console or Signal path and
then inspect the Langfuse project for OTel traces with `brain.trace_id` span
attributes.


------------------------------------------------------------------------
_End of Observability_
