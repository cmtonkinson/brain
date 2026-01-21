#!/usr/bin/env bash
set -euo pipefail

echo "Running lint and type checks..."

poetry run ruff check src test scripts alembic
poetry run black --check src test scripts alembic
poetry run mypy src test scripts alembic
poetry run pyright
