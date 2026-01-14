#!/usr/bin/env bash

docker-compose -f docker-compose.yml -f docker-compose.observability.yml stop \
  && docker-compose -f docker-compose.yml -f docker-compose.observability.yml rm -f \
  && docker-compose -f docker-compose.yml -f docker-compose.observability.yml up -d --force-recreate --remove-orphans --build

