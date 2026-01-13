# Brain Quick Start Guide

Get up and running in 10 minutes.

## Prerequisites Checklist

- [ ] MacOS (Apple Silicon recommended for Ollama performance)
- [ ] Docker Desktop installed and running
- [ ] Obsidian installed with vault created
- [ ] Obsidian plugins installed: Smart Connections, Local REST API
- [ ] Anthropic API key (get from console.anthropic.com)
- [ ] iPhone with Signal app installed

## Step-by-Step Setup

### 1. Install Ollama (5 minutes)

```bash
# Install via Homebrew
brew install ollama

# Start Ollama service
brew services start ollama

# Pull embedding model
ollama pull nomic-embed-text

# Verify it works
ollama list
```

### 2. Configure Obsidian (5 minutes)

**Install Plugins:**
1. Open Obsidian → Settings → Community Plugins
2. Turn off Safe Mode
3. Click Browse and install:
   - "Smart Connections"
   - "Local REST API"

**Configure Local REST API:**
1. Settings → Community Plugins → Local REST API
2. Click "Generate API Key" and save it
3. Note the server URL (default: `http://localhost:27123`)
4. Enable the plugin

**Test it works:**
```bash
# Replace YOUR_API_KEY with the key you generated
curl -H "Authorization: Bearer YOUR_API_KEY" http://localhost:27123/
```

### 3. Setup Brain Project (2 minutes)

```bash
# Extract the bootstrap zip to your home directory
cd ~
unzip brain-bootstrap.zip
cd brain

# Copy environment template
cp .env.example .env

# Edit .env with your actual values
nano .env  # or use your preferred editor
```

**Required values in .env:**
- `ANTHROPIC_API_KEY` - from console.anthropic.com
- `OBSIDIAN_API_KEY` - from step 2
- `OBSIDIAN_VAULT_PATH` - absolute path like `/Users/yourname/Documents/Vault`
- `POSTGRES_PASSWORD` - choose any secure password
- `USER` - your macOS username

**Optional values in .env:**
- `OLLAMA_EMBED_MODEL` - defaults to `mxbai-embed-large`
- `INDEXER_INTERVAL_SECONDS` - defaults to `0` (disabled)
- `INDEXER_CHUNK_TOKENS` - defaults to `1000`
- `INDEXER_COLLECTION` - defaults to `obsidian`

### 4. Install Python Dependencies (2 minutes)

```bash
# Install Poetry if needed
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install
```

### 5. Start Services (1 minute)

```bash
# Start all Docker containers
docker-compose up -d

# Check everything is running
docker-compose ps

# View logs
docker-compose logs -f
```

You should see:
- brain-qdrant (running)
- brain-redis (running)
- brain-postgres (running)
- brain-signal (running)
- brain-agent (running)

### 6. Link Signal Device (2 minutes)

```bash
# Get QR code
curl -X GET http://localhost:8080/v1/qrcodelink?device_name=brain

# This returns a QR code in the terminal
```

**On your iPhone:**
1. Open Signal
2. Tap your profile → Linked Devices
3. Tap "Link New Device"
4. Scan the QR code from terminal

### 7. Index Your Vault (1 minute)

```bash
# Run the indexer
poetry run python src/indexer.py

# Check Qdrant dashboard
open http://localhost:6333/dashboard
```
If you want automatic indexing, set `INDEXER_INTERVAL_SECONDS` in `.env` and restart the agent.

### 8. Test It! (1 minute)

**Send yourself a Signal message:**

```
"What's in my knowledge base?"
```

Your agent should respond!

## Troubleshooting

**Agent not responding?**
```bash
# Check logs
docker-compose logs -f agent

# Restart services
docker-compose restart agent
```

**Signal QR code not showing?**
```bash
# Check signal-api is running
docker-compose logs signal-api

# Restart it
docker-compose restart signal-api
```

**Ollama connection failed?**
```bash
# Check Ollama is running
ollama list

# If not, start it
brew services start ollama
```

**Obsidian API connection failed?**
- Verify Local REST API plugin is enabled in Obsidian
- Check the API key in `.env` matches the one in Obsidian
- Confirm Obsidian is running

## Next Steps

1. **Customize the agent** - Edit `src/agent.py` to add your own tools
2. **Add more tools** - Calendar, Reminders, etc. in `src/tools/`
3. **Set up launchd** - Make Brain start automatically on boot
4. **Explore Phase 2** - Add voice capabilities

## Daily Usage

**Start Brain:**
```bash
cd ~/brain
docker-compose up -d
```

**Stop Brain:**
```bash
docker-compose down
```

**View logs:**
```bash
docker-compose logs -f agent
```

**Re-index vault:**
```bash
poetry run python src/indexer.py --full-reindex
```

Enjoy your personal AI assistant! 🧠
