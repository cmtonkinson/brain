FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

ARG GITHUB_MCP_VERSION=0.28.1
RUN curl -fsSL -o /tmp/github-mcp-server.tar.gz \
    "https://github.com/github/github-mcp-server/releases/download/v${GITHUB_MCP_VERSION}/github-mcp-server_Linux_x86_64.tar.gz" \
    && tar -xzf /tmp/github-mcp-server.tar.gz -C /usr/local/bin github-mcp-server \
    && chmod +x /usr/local/bin/github-mcp-server \
    && rm /tmp/github-mcp-server.tar.gz

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install Poetry and dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --no-root

# Allow MCP tools with null output schemas (GitHub MCP server returns outputSchema=null for some tools).
RUN python - <<'PY'
from pathlib import Path

path = Path('/usr/local/lib/python3.11/site-packages/utcp_mcp/mcp_communication_protocol.py')
text = path.read_text(encoding='utf-8')
old = 'outputs=mcp_tool.outputSchema,'
new = 'outputs=mcp_tool.outputSchema or {},'
if old in text:
    path.write_text(text.replace(old, new), encoding='utf-8')
PY

# Treat structuredContent=None as absent so we can fall back to content parsing.
RUN python - <<'PY'
from pathlib import Path

path = Path('/usr/local/lib/python3.11/site-packages/utcp_mcp/mcp_communication_protocol.py')
text = path.read_text(encoding='utf-8')
old = "if hasattr(result, 'structuredContent'):"
new = "if hasattr(result, 'structuredContent') and result.structuredContent is not None:"
if old in text:
    path.write_text(text.replace(old, new), encoding='utf-8')
PY

# Allow string tool args (commonly used for search tools) by mapping to {"query": "..."}.
RUN python - <<'PY'
from pathlib import Path

path = Path('/usr/local/lib/python3.11/site-packages/utcp_code_mode/code_mode_utcp_client.py')
text = path.read_text(encoding='utf-8')
old = (
    "                if args is None:\\n"
    "                    args = kwargs\\n"
    "                try:\\n"
    "                    # Security logging for tool calls\\n"
    "                    logger.info(f\"Tool call: {tool_name_ref} with args: {list(args.keys()) if args else 'none'}\")\\n"
)
new = (
    "                if args is None:\\n"
    "                    args = kwargs\\n"
    "                if isinstance(args, str):\\n"
    "                    args = {\"query\": args}\\n"
    "                try:\\n"
    "                    # Security logging for tool calls\\n"
    "                    logger.info(f\"Tool call: {tool_name_ref} with args: {list(args.keys()) if isinstance(args, dict) else 'non-dict'}\")\\n"
)
if old in text:
    path.write_text(text.replace(old, new), encoding='utf-8')
PY

# Copy application code
COPY src/ ./src/
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/

# Create logs directory
RUN mkdir -p /app/logs

# Run agent
CMD ["python", "-u", "src/agent.py"]
