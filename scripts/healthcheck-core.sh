#!/bin/sh
set -eu

exec curl --silent --fail http://127.0.0.1:8898/health >/dev/null
