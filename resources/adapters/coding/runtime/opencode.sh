#!/usr/bin/env bash
# OpenCode agent install. Runs as root during the base image build.
set -euo pipefail
npm install --global opencode-ai
