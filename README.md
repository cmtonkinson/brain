# Brain
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
[![CI Tests](https://github.com/cmtonkinson/brain/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/cmtonkinson/brain/actions/workflows/tests.yml)
![Python: 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)

An exocortex for attention, memory, and action. Brain is a local-first AI system grounded in data sovereignty and
durable knowledge; "cognitive infrastructure" that prioritizes context, directs intent deliberately, and closes loops.

## Overview
_Conceptually_ Brain has three parts:
1. A **personal knowledge base**: durable, human-readable, locally-stored information. At its simplest, this could be a
   single (if very large) file.
2. A **reasoning engine**: an LLM used to interpret context, propose actions, explain decisions, and interact with you
   conversationally.
3. A **capability layer**: governed operations that interact with the real world (files, calendars, messaging, etc.) via
   native APIs or MCP Servers.

The **agent** serves to coordinate these concerns while keeping them separate, inspectable, and under your control.

_Technically_, the system takes advantage of Docker to isolate subsystems. In an ideal world every component would be
containerized, but for various reasons (security boundaries, usability, performance) there are a limited number of
services that need to run directly on your host system:
- Obsidian, with its various plugins &mdash; _required_
- Ollama for local chat and embedding &mdash; _optional_
- Any MCP Servers which require host access (e.g. for EventKit on MacOS) &mdash; _optional_
- The Host MCP Gateway proxy (an HTTP server) &mdash; _optional_

All other services are run with Docker Compose:
- Durable working state and application logs are kept in **Postgres**
- Object storage is provided by **MinIO**
- Caching and queueing are handled by **Redis**
- Semantic search for embeddings is powered by **Qdrant**
- Memory (short- and long-term) is managed by **Letta**
- Secure chat/messaging is run through **Signal**
- And the agent process itself, built with **Pydantic AI**, which uses
  - **LiteLLM** for model orchestration
  - **UTCP Code-Mode** for MCP tool discovery/execution

There is an optional OpenTelemetry-based observability stack (a separate but related Docker Compose) which leverages
**Prometheus**, **Loki**, and **Grafana**.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Obsidian Vault (Tier 0)                │
│          Canonical notes, decisions, and memory             │
└───────────────┬─────────────────────────────────────────────┘
                │ Local REST API (read/write)
                │
        ┌───────▼──────────────────────────────────────┐
        │           Brain Agent (Pydantic AI)          │
        │   LiteLLM routing + tools + access control   │
        └───────┬────────────┬────────────┬────────────┘
                │            │            │
          Signal API       Qdrant     Postgres/Redis
          (E2EE I/O)     (embeddings)  (state/logs)
                │
                ▼
          Code-Mode (UTCP)
                │
        MCP servers (filesystem, EventKit, GitHub)
                │
        host-mcp-gateway (macOS APIs, optional)

        Letta (MemGPT) runs as a parallel service for
        archival memory and tool-augmented recall.
```

## Data Tiers (Current State)

**Tier 0 — Authoritative**
- Obsidian vault (canonical notes, promoted memory)
- Configuration/policy files under `~/.config/brain`

**Tier 1 — Durable system state**
- Postgres (action logs, operational state)
- Letta internal DB (archival memory state)
- Signal CLI state (device + message metadata)

**Tier 2 — Derived / cache**
- Qdrant embeddings and indexes
- Summaries and derived artifacts

## Phased Implementation

### Phase 1: Text interaction + memory + MCP tools (current)
- Obsidian Local REST API integration (read/write)
- Letta archival memory
- Code-Mode (UTCP) for MCP tool calls
- Signal messaging with allowlisted senders
- Vault indexer + Qdrant semantic search
- Optional observability stack (OTel)

### Phase 2: The "Assitant Triangle"
- Skill framework + capability registry
- Attention router + interruption policy
- Commitment tracking + loop closure

### Phase 3: Voice + telephony + SMS (combined)
- Local voice (whisper.cpp + Piper)
- POTS phone support (Twilio Media Streams)
- SMS fallback (Google Voice)

## Prerequisites

- macOS host (for EventKit MCP and host gateway)
- Docker + Docker Compose
- Python 3.13
- Obsidian + Local REST API plugin
- Optional: Ollama for local embeddings

### Obsidian setup
1. Install Obsidian from https://obsidian.md
2. Enable the **Local REST API** community plugin
3. Generate an API key and note the URL (default `http://localhost:27123`)

## Quick Start

### 1) Clone and install Python deps
```bash
cd ~
git clone <your-repo> brain
cd brain

# Install Poetry if needed
curl -sSL https://install.python-poetry.org | python3 -
poetry install
```

### 2) Configure Brain
```bash
mkdir -p ~/.config/brain

# Base config (override defaults as needed)
cp config/brain.yml ~/.config/brain/brain.yml

# Secrets
cp config/secrets.yml.sample ~/.config/brain/secrets.yml
chmod 600 ~/.config/brain/secrets.yml

# MCP/UTCP tool config (optional but recommended)
cp utcp.json.sample ~/.config/brain/utcp.json
```

Update `~/.config/brain/brain.yml` and `~/.config/brain/secrets.yml` with:
- `obsidian.vault_path` (absolute path)
- `obsidian.api_key` + `obsidian.url`
- `signal.phone_number` and `signal.allowed_senders_by_channel`
- `database.postgres_password` (for Postgres)
- `letta.server_password` (if using Letta)

If using Docker Compose, copy the env file and keep passwords in sync:
```bash
cp .env.sample .env
```
Update `.env` with `OBSIDIAN_VAULT_PATH`, `POSTGRES_PASSWORD`, and `LETTA_SERVER_PASSWORD`.

### 3) Start Docker services
```bash
docker-compose up -d
```

This starts:
- `brain-agent` (Pydantic AI)
- Qdrant (vectors)
- Postgres (state)
- Redis (queue/cache)
- signal-cli-rest-api (Signal)
- Letta (optional memory service)

### 4) Register Signal account
```bash
curl -X POST "http://localhost:8080/v1/register/+1XXXXXXXXXX"
```
Follow the verification flow from `signal-cli-rest-api` if prompted.

### 5) Index your Obsidian vault
```bash
docker-compose exec agent poetry run python src/indexer.py
```

### 6) (Optional) Bootstrap Letta tools
```bash
docker-compose exec agent python src/letta_bootstrap.py
```
Run this once after configuring Letta or changing Letta tool code.

## MCP Integrations (Code-Mode)

Brain uses UTCP Code-Mode to discover and call MCP servers. Configure your MCP servers in `~/.config/brain/utcp.json` (see `utcp.json.sample`).

For macOS-only MCP servers (like EventKit), run the host gateway on your Mac:
```bash
cd host-mcp-gateway

go build -o host-mcp-gateway ./...
./host-mcp-gateway -config ~/.config/brain/host-mcp-gateway.json
```

See `host-mcp-gateway/README.md` and `docs/mcp_servers.md` for details.

## Development Workflow

### View logs
```bash
docker-compose logs -f
```

### Rebuild after code changes
```bash
docker-compose up -d --build agent
```

### Run the agent locally (no Docker)
```bash
poetry run python src/agent.py --test "What's in my knowledge base?"
```

### Observability stack (optional)
```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

## Configuration

Defaults live in `config/brain.yml`. Override in `~/.config/brain/brain.yml` and store secrets in `~/.config/brain/secrets.yml`. Environment variables still override YAML (useful for CI or Docker).

```yaml
obsidian:
  vault_path: "/Users/you/Documents/Vault"
  url: "http://host.docker.internal:27123"
  api_key: "your-obsidian-api-key"

llm:
  model: "anthropic:claude-sonnet-4-20250514"
  timeout: 600
  embed_model: "mxbai-embed-large"
  embed_base_url: "http://host.docker.internal:11434"

signal:
  phone_number: "+15551234567"
  allowed_senders_by_channel:
    signal:
      - "+15551234567"

database:
  postgres_password: "secure-password-here"

letta:
  base_url: "http://letta:8283"
  server_password: "letta-password"
  agent_name: "brain"
```

## Usage

Send messages to your Signal account:

```
"Remind me to follow up next Tuesday"
"What did I decide about the website redesign?"
"Summarize my notes on Ruby performance"
"Create a note in Ideas/NewIdea.md with ..."
```

## Troubleshooting

### Agent not responding to Signal messages
1. Check agent logs: `docker-compose logs -f agent`
2. Verify Signal API: `curl http://localhost:8080/v1/about`
3. Confirm sender is allowlisted in `~/.config/brain/secrets.yml`

### Qdrant not indexing
1. Run: `poetry run python src/indexer.py --verbose`
2. Verify `obsidian.vault_path` matches the mounted path
3. Check Qdrant UI: http://localhost:6333/dashboard

### Letta memory not responding
1. Verify `LETTA_SERVER_PASSWORD` and `letta.base_url`
2. Run `docker-compose exec agent python src/letta_bootstrap.py`

### Code-Mode tools missing
1. Confirm `~/.config/brain/utcp.json` exists
2. Run the host gateway if using macOS-only servers

## Backup Strategy

### What to back up
- Obsidian vault (Tier 0)
- `~/.config/brain/*` (config + secrets)
- `data/postgres` and `data/letta` (Tier 1)
- `data/signal` (Signal device state)

### What you can regenerate
- Qdrant embeddings (`data/qdrant`)
- Redis cache (`data/redis`)

## Security Notes

- **Allowlist enforced**: Signal senders must be explicitly allowed.
- **Secrets stay local**: store API keys in `~/.config/brain/secrets.yml` or env vars.
- **Trust boundaries**: ingested data and external APIs are treated as untrusted.

## Roadmap

- [ ] Phase 1 hardening + stability work
- [ ] Phase 2: Triangle PRDs (attention router, commitments, skills)
- [ ] Phase 3: Voice + telephony + SMS
- [ ] Universal ingestion pipeline + object storage
- [ ] Policy engine + autonomy levels

## Contributing

This is a personal project, but feel free to fork and adapt for your own use.

## License

MIT (or choose your own)
