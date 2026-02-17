#!/usr/bin/env bash

BDC='docker-compose -f docker-compose.yml -f docker-compose.observability.yml'

$BDC stop && \
  $BDC rm -f && \
  $BDC up -d --force-recreate --remove-orphans --build

