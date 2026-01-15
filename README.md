# Brain

A privacy-first, MacOS-native personal AI assistant with end-to-end encrypted messaging, local knowledge management, and pluggable LLM architecture.

## Overview

Brain is a modular personal assistant that:
- Uses **Obsidian** as the canonical knowledge base (notes, conversations, extracted facts)
- Communicates via **Signal** with E2EE for remote text commands
- Runs entirely on your MacBook with **local data sovereignty**
- Supports **pluggable LLM backends** (Claude via API, future local models via Ollama)
- Integrates with MacOS apps (Calendar, Reminders, Messages) via **Hammerspoon** and **PyXA**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Obsidian Vault                          │
│          (Canonical source: notes, conversations)            │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ├─→ Smart Connections (UI semantic search)
                   │
                   └─→ Qdrant + Ollama embeddings (agent access)
                              ↓
                   ┌──────────────────────┐
                   │   Pydantic AI Agent   │
                   │   + LiteLLM           │
                   └──────────┬────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ↓                 ↓                  ↓
       PostgreSQL        Signal (E2EE)    Hammerspoon
    (operational state)   (messaging)   (MacOS integration)
```

### Data Model

**Canonical (long-term):**
- Obsidian vault: knowledge notes, conversation transcripts, extracted facts
- Backed up via Git/cloud sync

**Operational (short-term):**
- PostgreSQL: pending tasks, action logs, queue state
- Regeneratable or archived to Obsidian

**Derived (regeneratable):**
- Qdrant: embeddings of Obsidian content
- Smart Connections cache

## Phased Implementation

### Phase 1: Text interaction, PKM, and agentic actions ← **YOU ARE HERE**
- Obsidian + Smart Connections + Local REST API
- Qdrant vector database
- Ollama (local embeddings)
- LiteLLM (LLM abstraction)
- Pydantic AI (agent orchestration)
- PostgreSQL (operational state)
- signal-cli (E2EE messaging)
- Hammerspoon (system integration)

### Phase 2: Local voice interaction
- whisper.cpp (STT, Metal-optimized)
- Piper (local TTS)
- openWakeWord (custom wake word)

### Phase 3: POTS phone support
- Twilio Voice + Media Streams
- WebSocket real-time audio

### Phase 4: SMS fallback
- Google Voice integration (non-E2EE convenience)

## Prerequisites

### Native MacOS Tools (install first)
```bash
# Ollama (for local embeddings)
brew install ollama
ollama pull nomic-embed-text

# signal-cli (will be containerized via signal-cli-rest-api)
# No need to install if using Docker approach

# Obsidian (download from obsidian.md)
# Install plugins: Smart Connections, Local REST API
```

### Obsidian Setup
1. Install Obsidian from https://obsidian.md
2. Create or open your vault
3. Install community plugins:
   - **Smart Connections**: Settings → Community Plugins → Browse → "Smart Connections"
   - **Local REST API**: Settings → Community Plugins → Browse → "Local REST API"
4. Configure Local REST API:
   - Enable the plugin
   - Generate an API key
   - Note the URL (default: `http://localhost:27123`)

## Quick Start

### 1. Clone and setup
```bash
cd ~
git clone <your-repo> brain  # Or extract the bootstrap zip
cd brain
```

### 2. Configure Brain (YAML)
```bash
mkdir -p ~/.config/brain
cp config/brain.yml ~/.config/brain/brain.yml
cp config/secrets.yml.sample ~/.config/brain/secrets.yml
chmod 600 ~/.config/brain/secrets.yml

# Edit the files with your values:
# - obsidian.vault_path (absolute path to your vault)
# - obsidian.api_key (from Local REST API plugin)
# - signal.allowed_senders_by_channel (Signal allowlist)
# - anthropic_api_key (from console.anthropic.com, if using Claude)
# - postgres_password (if using Postgres)
```
If you're using Docker, set `POSTGRES_PASSWORD` in `.env` (used by Docker Compose) to match your `postgres_password`.
```bash
cp .env.sample .env
```
Keep these in sync between `.env` (Docker Compose) and YAML config:
- `POSTGRES_PASSWORD` ↔ `database.postgres_password`
- `OBSIDIAN_VAULT_PATH` ↔ `obsidian.vault_path` (volume mount path)
- `OLLAMA_URL` ↔ `ollama.url` (used by Letta container)
- `LETTA_SERVER_PASSWORD` ↔ `letta.server_password`

### 3. Install Python dependencies
```bash
# Install Poetry if you don't have it
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install
```

### 4. Start Docker services
```bash
docker-compose up -d
```

This starts:
- Qdrant (vector database) on port 6333
- Redis (task queue) on port 6379
- PostgreSQL (operational state) on port 5432
- signal-cli-rest-api (Signal messaging) on port 8080
- brain-agent (your AI assistant)

### 5. Register Signal account
```bash
# Register a new Signal account with your Google Voice number
# Replace +1XXXXXXXXXX with your Google Voice number
curl -X POST "http://localhost:8080/v1/register/+1XXXXXXXXXX"

# If Signal requires a captcha, solve it at:
# https://signalcaptchas.org/registration/generate.html
# Then pass the full signalcaptcha://... token as JSON:
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"captcha":"signalcaptcha://signal-hcaptcha..."}' \
  "http://localhost:8080/v1/register/+1XXXXXXXXXX"

# Signal will send an SMS verification code to your Google Voice number
# Once you receive the code, verify:
curl -X POST "http://localhost:8080/v1/register/+1XXXXXXXXXX/verify/XXXXXX"
# Replace XXXXXX with the 6-digit code from the SMS

# If SMS doesn't arrive, request voice verification instead:
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"captcha":"signalcaptcha://signal-hcaptcha...","voice":true}' \
  "http://localhost:8080/v1/register/+1XXXXXXXXXX"
```

### 6. Index your Obsidian vault
```bash
docker-compose exec agent poetry run python src/indexer.py
```
Optional: set `INDEXER_INTERVAL_SECONDS` to schedule automatic indexing; the agent tool `index_vault` can also be invoked to trigger a manual reindex.

### 7. Test the agent
```bash
# Send a Signal message to yourself
# The agent should respond

# Or test locally:
poetry run python src/agent.py --test "What's in my knowledge base?"
```

## Development Workflow

### View logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f agent
```

### Rebuild after code changes
```bash
docker-compose up -d --build agent
```

### Access PostgreSQL
```bash
docker-compose exec postgres psql -U brain -d brain
```

### Access Qdrant UI
Open http://localhost:6333/dashboard

### Re-index Obsidian vault
```bash
docker-compose exec agent poetry run python src/indexer.py --full-reindex
```

## Project Structure

```
brain/
├── docker-compose.yml       # Service orchestration
├── Dockerfile              # Agent container definition
├── pyproject.toml          # Python dependencies
├── config/brain.yml        # Checked-in defaults (non-secret)
├── config/secrets.yml.sample # Secrets template
├── .env.sample             # Docker Compose env template
├── README.md               # This file
├── data/                   # Docker volumes (gitignored)
│   ├── qdrant/            # Vector database storage
│   ├── redis/             # Redis persistence
│   ├── postgres/          # PostgreSQL data
│   └── signal/            # Signal-cli data
├── logs/                   # Application logs
└── src/
    ├── agent.py           # Main agent daemon
    ├── indexer.py         # Obsidian vault indexer
    ├── signal_handler.py  # Signal message handling
    ├── models.py          # Data models
    ├── config.py          # Configuration loading
    └── tools/             # Agent tools
        ├── obsidian.py    # Obsidian API wrapper
        ├── calendar.py    # Calendar integration
        └── reminders.py   # Reminders integration
```

## Configuration

### YAML Configuration

Defaults live in `config/brain.yml`. Override in `~/.config/brain/brain.yml` and store secrets in `~/.config/brain/secrets.yml`. Docker Compose mounts `~/.config/brain` into the container at `/config`, and the loader checks both paths.

**Precedence (highest to lowest):**
- Environment variables
- `~/.config/brain/secrets.yml` (or `/config/secrets.yml` in containers)
- `~/.config/brain/brain.yml` (or `/config/brain.yml` in containers)
- `config/brain.yml`

```yaml
obsidian:
  vault_path: "/Users/you/Documents/Vault"
  api_key: "your-obsidian-api-key"

signal:
  allowed_senders_by_channel:
    signal:
      - "+15551234567"

anthropic_api_key: "sk-ant-..."
database:
  postgres_password: "secure-password-here"
```
Environment variables still override YAML (useful for CI or Docker).

## Usage

### Text Commands via Signal

Send messages to yourself via Signal:

```
"Remind me to call Mom tomorrow at 2pm"
"What did I decide about the website redesign?"
"Summarize my notes on Ruby performance"
"Add a calendar event: dentist appointment Friday 10am"
```

### Local Hammerspoon Triggers (coming soon)

Hotkey → agent command → notification

## Troubleshooting

### Agent not responding to Signal messages
1. Check agent logs: `docker-compose logs -f agent`
2. Verify Signal linking: `curl http://localhost:8080/v1/about`
3. Test Signal send: `curl -X POST http://localhost:8080/v2/send -H "Content-Type: application/json" -d '{"number":"+your-number","recipients":["+your-number"],"message":"test"}'`

### Qdrant not indexing
1. Check indexer logs: `poetry run python src/indexer.py --verbose`
2. Verify Obsidian vault path in `~/.config/brain/brain.yml`
3. Check Qdrant UI: http://localhost:6333/dashboard

### Ollama embeddings failing
1. Verify Ollama is running: `ollama list`
2. Check model is downloaded: `ollama pull nomic-embed-text`
3. Test embeddings: `ollama embeddings model nomic-embed-text prompt "test"`

### Database connection errors
1. Check PostgreSQL is running: `docker-compose ps postgres`
2. Verify password in `~/.config/brain/secrets.yml` matches docker-compose `.env`
3. Check logs: `docker-compose logs postgres`

## Backup Strategy

### What to backup
```bash
# Canonical data (critical)
~/Documents/ObsidianVault/     # Your knowledge base (already backed up via Git/iCloud?)

# Operational data (nice to have)
~/brain/data/postgres/         # Task history, action logs

# Configuration
~/.config/brain/brain.yml      # Non-secret config
~/.config/brain/secrets.yml    # API keys, passwords
```

### What you can regenerate
- Qdrant embeddings (re-run indexer)
- Redis cache
- Smart Connections cache

### Recommended backup
```bash
# Automated via Time Machine or:
rsync -av ~/brain/data/postgres/ /backup/brain-postgres/
# Exclude: data/qdrant, data/redis (regeneratable)
```

## Security Notes

- **API Keys**: Never commit `~/.config/brain/secrets.yml` to version control
- **Signal E2EE**: All messages encrypted end-to-end between your devices
- **Local Data**: Everything runs on your Mac; LLM API calls are the only external dependency
- **Future**: Consider encrypting PostgreSQL data at rest

## Roadmap

- [ ] Phase 1: Basic text agent (in progress)
- [ ] Add MemGPT/Letta for advanced memory management
- [ ] Phase 2: Voice interface (whisper.cpp + Piper)
- [ ] Phase 3: POTS phone calls (Twilio)
- [ ] Phase 4: SMS fallback (Google Voice)
- [ ] Multi-agent workflows (research, writing, coding)
- [ ] Scheduled automations (morning briefing, reminder checks)

## Contributing

This is a personal project, but feel free to fork and adapt for your own use.

## License

MIT (or choose your own)
