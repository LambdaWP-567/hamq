# =============================================================================
# HAMq Producer — combined multi-stage image (build context: components/producer/)
#
# Stage 1 : Node 20 — build the React/Vite SPA into /dist
# Stage 2 : Python 3.12 — FastAPI backend + SPA served as static files
#
# Build arguments:
#   VITE_API_BASE_URL  injected into the React build (default: relative path)
#
# Exposed port: 8000
# =============================================================================

# ─── Stage 1: React frontend ─────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install deps before copying source to exploit Docker layer caching
COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ ./

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# Vite outputs to dist/ by default
RUN npm run build

# ─── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG APP_VERSION=1.0.0
ENV APP_VERSION=${APP_VERSION}

LABEL org.opencontainers.image.title="HAMq Producer" \
      org.opencontainers.image.description="Resilient Kafka message producer — FastAPI + React UI" \
      org.opencontainers.image.version="${APP_VERSION}"

# Install curl for the Docker HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security; matches the UID used in the Helm chart
RUN groupadd --gid 1000 hamq && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false hamq

WORKDIR /app

# Python dependencies (cached separately from app code)
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY backend/app/ ./app/

# Compiled SPA — FastAPI StaticFiles serves this at "/"
COPY --from=frontend-builder /app/backend/static ./static/

# PVC will be mounted at /data in Kubernetes; create it for local docker runs
RUN mkdir -p /data && chown hamq:hamq /data

USER hamq

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Single worker — the SQLite buffer and asyncio tasks are not multiprocess-safe.
# Use multiple Pods (Helm replicaCount) for horizontal scaling instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
