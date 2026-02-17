#!/usr/bin/env bash

# Ensure there are arguments
if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <prompt>"
  exit 1
fi

docker-compose -f docker-compose.yml exec -it agent python -u src/agent.py --test "$@"
