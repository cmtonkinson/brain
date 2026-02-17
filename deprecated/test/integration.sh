#!/usr/bin/env bash
set -euo pipefail

echo "Running integration tests..."

RUN_INTEGRATION=false
while (( "$#" )); do
  case "$1" in
    --integration) RUN_INTEGRATION=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--integration]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "${BRAIN_RUN_INTEGRATION:-}" == "1" ]]; then
  RUN_INTEGRATION=true
fi

if ! $RUN_INTEGRATION; then
  echo "Skipping integration tests (pass --integration or -a to run)."
  exit 0
fi

container_name=""
qdrant_container=""

cleanup() {
  if [[ -n "$container_name" ]]; then
    echo "Stopping Postgres integration container: ${container_name}"
    docker stop "$container_name" >/dev/null
  fi
  if [[ -n "$qdrant_container" ]]; then
    echo "Stopping Qdrant integration container: ${qdrant_container}"
    docker stop "$qdrant_container" >/dev/null
  fi
}

trap cleanup EXIT

start_postgres_container() {
  local image="${BRAIN_PG_IMAGE:-postgres:16-alpine}"
  local port

  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not available; set DATABASE_URL to run integration tests."
    exit 0
  fi

  container_name="brain-test-pg-$RANDOM-$$"

  echo "Starting Postgres integration container: ${container_name}"
  docker run -d --rm \
    --name "$container_name" \
    -e POSTGRES_USER=brain \
    -e POSTGRES_PASSWORD=brain \
    -e POSTGRES_DB=brain \
    -p 127.0.0.1::5432 \
    "$image" >/dev/null

  port="$(docker port "$container_name" 5432/tcp | head -n1 | awk -F: '{print $NF}')"
  if [[ -z "$port" ]]; then
    echo "Failed to discover Postgres port."
    docker stop "$container_name" >/dev/null
    exit 1
  fi

  export DATABASE_URL="postgresql://brain:brain@localhost:${port}/brain"

  for _ in {1..30}; do
    if docker exec "$container_name" pg_isready -U brain -d brain >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "Postgres did not become ready in time."
  exit 1
}

start_qdrant_container() {
  local image="${BRAIN_QDRANT_IMAGE:-qdrant/qdrant:v1.16.2}"
  local port

  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker not available; set QDRANT_URL to run Qdrant integration tests."
    exit 0
  fi

  qdrant_container="brain-test-qdrant-$RANDOM-$$"

  echo "Starting Qdrant integration container: ${qdrant_container}"
  docker run -d --rm \
    --name "$qdrant_container" \
    -p 127.0.0.1::6333 \
    "$image" >/dev/null

  port="$(docker port "$qdrant_container" 6333/tcp | head -n1 | awk -F: '{print $NF}')"
  if [[ -z "$port" ]]; then
    echo "Failed to discover Qdrant port."
    docker stop "$qdrant_container" >/dev/null
    exit 1
  fi

  export QDRANT_URL="http://localhost:${port}"

  for _ in {1..30}; do
    if curl -fsS "http://localhost:${port}/collections" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "Qdrant did not become ready in time."
  exit 1
}

if [[ -z "${DATABASE_URL:-}" ]]; then
  start_postgres_container
fi

if [[ -z "${QDRANT_URL:-}" ]]; then
  start_qdrant_container
fi

run_pytest() {
  set +e
  poetry run pytest "$@"
  status=$?
  set -e
  if [[ $status -ne 0 && $status -ne 5 ]]; then
    exit $status
  fi
}

run_pytest test/integration
