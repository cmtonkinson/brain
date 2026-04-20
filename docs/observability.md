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

The overlay adds:
- `otel-collector`: receives Brain OTLP over HTTP and forwards traces to
  Langfuse.
- `langfuse-web`: web UI and API at `http://localhost:3000`.
- `langfuse-worker`: background ingestion and processing.
- `clickhouse`: Langfuse event analytics storage.
- `seaweedfs`: S3-compatible blob storage for Langfuse raw events, media, and
  exports.
- `seaweedfs-bucket-init`: creates the `langfuse` bucket.
- `langfuse-postgres-init`: creates the dedicated `langfuse` Postgres user and
  database in the existing `postgres` service.

Brain's existing Postgres and Redis services are reused. Langfuse data must stay
in its own Postgres database and SeaweedFS prefixes; it is operational
observability data, not Brain domain state or OAS-managed object data.

------------------------------------------------------------------------
## Connection Map
Local operator endpoints:

| Surface | URL | Notes |
|---|---|---|
| Langfuse UI | `http://localhost:3000` | Login with `LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD`. |
| OTel Collector HTTP | `http://localhost:4318` | Brain sends OTLP here when observability is enabled. |
| SeaweedFS S3 API | `http://localhost:8333` | Local S3-compatible endpoint for inspection and smoke tests. |
| ClickHouse HTTP | `http://127.0.0.1:8123` | Bound to localhost by default. |
| ClickHouse native | `127.0.0.1:9000` | Bound to localhost by default. |

Container-to-container endpoints:

| Consumer | Target | Purpose |
|---|---|---|
| `brain-core`, `brain-agent` | `http://otel-collector:4318` | OTLP trace and metric export. |
| `otel-collector` | `http://langfuse-web:3000/api/public/otel` | Langfuse OTel ingestion. |
| `langfuse-web`, `langfuse-worker` | `postgres:5432/langfuse` | Dedicated Langfuse Postgres database. |
| `langfuse-web`, `langfuse-worker` | `redis:6379` | Langfuse queue/cache use. |
| `langfuse-web`, `langfuse-worker` | `http://clickhouse:8123` and `clickhouse:9000` | Langfuse analytics storage and migrations. |
| `langfuse-web`, `langfuse-worker` | `http://seaweedfs:8333` | S3-compatible event/media/export blobs. |

------------------------------------------------------------------------
## Required Secrets
Create or update `.env` at the repository root. Values must be stable across
restarts because Langfuse persists encrypted data and database credentials.

Generate runtime secrets:
```sh
LANGFUSE_POSTGRES_PASSWORD="$(openssl rand -base64 32)"
LANGFUSE_CLICKHOUSE_USER=clickhouse
LANGFUSE_CLICKHOUSE_PASSWORD="$(openssl rand -base64 32)"
LANGFUSE_NEXTAUTH_URL=http://localhost:3000
LANGFUSE_NEXTAUTH_SECRET="$(openssl rand -base64 32)"
LANGFUSE_SALT="$(openssl rand -base64 32)"
LANGFUSE_ENCRYPTION_KEY="$(openssl rand -hex 32)"
SEAWEEDFS_S3_ACCESS_KEY_ID="brain-langfuse-$(openssl rand -hex 8)"
SEAWEEDFS_S3_SECRET_ACCESS_KEY="$(openssl rand -base64 32)"
```

`LANGFUSE_ENCRYPTION_KEY` must be exactly 64 hex characters. `openssl rand -hex
32` produces the correct shape.

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

The current compose overlay starts SeaweedFS S3 without credential enforcement.
The SeaweedFS access key and secret are still supplied to Langfuse and the
bucket-init container for S3 client signing. For network exposure beyond local
Docker development, add a SeaweedFS S3 config file and enforce those
credentials.

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
- `seaweedfs-bucket-init` exits successfully after creating the `langfuse`
  bucket if missing.
- `brain-core` and `brain-agent` set observability enabled via compose
  environment overrides.
- The Langfuse UI is reachable at `http://localhost:3000`.

To verify trace flow, send one Brain turn through the console or Signal path and
then inspect the Langfuse project for OTel traces with `brain.trace_id` span
attributes.


------------------------------------------------------------------------
_End of Observability_
