#!/usr/bin/env bash

docker-compose \
  -f docker-compose.yml \
  -f docker-compose.observability.yml \
  up \
  --detach \
  --force-recreate \
  --no-deps \
  --build \
  --remove-orphans \
  agent celery-worker celery-beat

