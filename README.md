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

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your values:
# - ANTHROPIC_API_KEY (from console.anthropic.com)
# - OBSIDIAN_API_KEY (from Local REST API plugin)
# - OBSIDIAN_VAULT_PATH (absolute path to your vault)
# - POSTGRES_PASSWORD (choose a secure password)
```

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
├── .env                    # Configuration (gitignored)
├── .env.example            # Configuration template
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

### Environment Variables (.env)

```bash
# LLM API Keys
ANTHROPIC_API_KEY=sk-ant-...           # Claude API key

# Obsidian
OBSIDIAN_API_KEY=your-api-key-here     # From Local REST API plugin
OBSIDIAN_VAULT_PATH=/Users/you/Documents/Vault  # Absolute path; mounted into container at same path
OBSIDIAN_URL=http://host.docker.internal:27123

# Database
POSTGRES_PASSWORD=secure-password-here

# Ollama (local embeddings)
OLLAMA_URL=http://host.docker.internal:11434

# Internal (set by docker-compose)
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379
DATABASE_URL=postgresql://brain:${POSTGRES_PASSWORD}@postgres:5432/brain

# Optional
LITELLM_BASE_URL=

# User context
USER=your-username
```

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
2. Verify Obsidian vault path in .env
3. Check Qdrant UI: http://localhost:6333/dashboard

### Ollama embeddings failing
1. Verify Ollama is running: `ollama list`
2. Check model is downloaded: `ollama pull nomic-embed-text`
3. Test embeddings: `ollama embeddings model nomic-embed-text prompt "test"`

### Database connection errors
1. Check PostgreSQL is running: `docker-compose ps postgres`
2. Verify password in .env matches docker-compose.yml
3. Check logs: `docker-compose logs postgres`

## Backup Strategy

### What to backup
```bash
# Canonical data (critical)
~/Documents/ObsidianVault/     # Your knowledge base (already backed up via Git/iCloud?)

# Operational data (nice to have)
~/brain/data/postgres/         # Task history, action logs

# Configuration
~/brain/.env                   # API keys, passwords
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

- **API Keys**: Never commit `.env` to version control
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
