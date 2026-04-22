ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock /app/

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl nodejs npm && \
    rm -rf /var/lib/apt/lists/* && \
    uv sync --frozen --no-cache

COPY . /app

RUN addgroup --system brain && \
    adduser --system --ingroup brain brain && \
    chown -R brain:brain /app

USER brain

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "--silent", "--fail", "http://127.0.0.1:8763/health"]

CMD ["python", "-m", "main"]
