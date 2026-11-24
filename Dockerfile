# ---- Stage 1: build the React app (TypeScript check + Vite build) ----
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: the API, serving the built app ----
FROM python:3.12-slim

# Pinned AviationStack MCP server (needs Python >= 3.13; uv downloads that
# interpreter at build time, so nothing is fetched at runtime).
ARG AVIATIONSTACK_MCP_VERSION=1.8.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/tripmate \
    UV_TOOL_DIR=/opt/uv/tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    AVIATIONSTACK_MCP_VERSION=${AVIATIONSTACK_MCP_VERSION}

WORKDIR /app

RUN groupadd --system --gid 10001 tripmate \
    && useradd --system --uid 10001 --gid tripmate \
        --home-dir /home/tripmate --create-home \
        --shell /usr/sbin/nologin tripmate

# Fully pinned dependency set (see requirements.txt / requirements.lock).
COPY requirements.txt requirements.lock ./

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.lock \
    && uv tool install --python 3.13 "aviationstack-mcp==${AVIATIONSTACK_MCP_VERSION}" \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')" \
    && chmod -R a+rX /opt/uv /opt/tiktoken

COPY --chown=tripmate:tripmate . .
COPY --from=frontend --chown=tripmate:tripmate /build/dist /app/frontend/dist

USER tripmate

EXPOSE 8014

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8014/health', timeout=3)"]

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8014"]
