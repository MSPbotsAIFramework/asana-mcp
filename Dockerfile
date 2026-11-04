# Multi-stage build for a small, reproducible image.
FROM python:3.12-slim AS builder

ARG VERSION="unknown"
ARG COMMIT_SHA="unknown"
ARG BUILD_DATE="unknown"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Production stage -- slim image, no uv, no build tools.
FROM python:3.12-slim AS production

RUN groupadd -g 1001 asana && \
    useradd -u 1001 -g asana -s /bin/sh -m asana

# python:3.12-slim ships neither curl nor wget; the HEALTHCHECK below needs one.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder --chown=asana:asana /app/.venv /app/.venv
COPY --from=builder --chown=asana:asana /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"
ENV MCP_HTTP_PORT=8080
ENV MCP_HTTP_HOST=0.0.0.0

USER asana
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python", "-m", "asana_mcp"]

LABEL org.opencontainers.image.title="asana-mcp"
LABEL org.opencontainers.image.description="Asana MCP server for the MSPbots Agent platform"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${COMMIT_SHA}"
LABEL org.opencontainers.image.licenses="Apache-2.0"
