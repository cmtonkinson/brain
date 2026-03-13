#!/bin/sh
set -eu

heartbeat_file="${BRAIN_AGENT_HEARTBEAT_FILE:-/run/brain/agent-heartbeat}"
max_age_seconds="${BRAIN_AGENT_HEARTBEAT_MAX_AGE_SECONDS:-90}"

test -f "$heartbeat_file"

current_epoch="$(date +%s)"
heartbeat_epoch="$(stat -c %Y "$heartbeat_file")"
heartbeat_age="$((current_epoch - heartbeat_epoch))"

test "$heartbeat_age" -lt "$max_age_seconds"
exec curl --silent --fail http://brain-core:8898/health >/dev/null
