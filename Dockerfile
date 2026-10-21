# syntax=docker/dockerfile:1

# One image with everything: the FastAPI backend serves the built Svelte UI at "/".

# --- frontend build (runs on the build host's architecture, the output is plain static files)
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
RUN corepack enable && corepack prepare pnpm@10 --activate
WORKDIR /frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# --- backend dependencies + package, installed into a venv
FROM python:3.13-slim-bookworm AS backend
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- runtime
FROM python:3.13-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 ghg \
    && mkdir /data && chown ghg:ghg /data

COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /frontend/dist /app/frontend

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GHG_HOST=0.0.0.0 \
    GHG_PORT=8000 \
    GHG_DATA_DIR=/data \
    GHG_FRONTEND_DIR=/app/frontend

USER ghg
WORKDIR /app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["ghgtracker"]
