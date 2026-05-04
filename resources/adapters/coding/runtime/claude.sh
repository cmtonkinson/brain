#!/usr/bin/env bash
# Claude Code agent install. Runs as root during the base image build.
set -euo pipefail
npm install --global @anthropic-ai/claude-code
