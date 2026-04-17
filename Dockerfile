ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PIP_NO_CACHE_DIR=1 \
  PYTHONPATH=/app \
  BRAIN_CORE_CONFIG_FILE=/app/config/core.yaml \
  BRAIN_RESOURCES_CONFIG_FILE=/app/config/resources.yaml \
  BRAIN_ACTORS_CONFIG_FILE=/app/config/actors.yaml

WORKDIR /app
COPY requirements.txt /app/requirements.txt

RUN apt-get update && \
  apt-get install -y --no-install-recommends curl && \
  rm -rf /var/lib/apt/lists/* && \
  pip install --upgrade pip && \
  pip install --requirement /app/requirements.txt

COPY . /app

RUN addgroup --system brain && \
  adduser --system --ingroup brain brain && \
  mkdir -p /run/brain && \
  printf '%s\n' '#!/bin/sh' 'set -eu' 'echo "brain-healthcheck script not mounted" >&2' 'exit 1' >/usr/local/bin/brain-healthcheck && \
  chmod +x /usr/local/bin/brain-healthcheck && \
  chown -R brain:brain /app /run/brain

USER brain

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=3 \
  CMD ["/usr/local/bin/brain-healthcheck"]

