# ============================================================================
# HAMq Consumer — Multi-stage Dockerfile
# ============================================================================
# Stage 1 : Build the React SPA (Node 20 + Vite)
# Stage 2 : Python 3.12 runtime — copies the compiled SPA into backend/static
#           so FastAPI serves it as static files on "/"
#
# Build args:
#   VITE_API_BASE_URL  — injected into the React build (default: empty string
#                        so all API calls are relative to the same host)
#
# Environment variables at runtime:
#   See app/config.py — every field can be overridden via env vars.
#
# Exposed port: 8001
# ============================================================================

# ──────────────────────────────────────────────────────────────────────────────
# Stage 1 — Frontend build
# ──────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies before copying source so Docker layer caching kicks in
# when only source files change.
COPY frontend/package*.json ./
RUN npm ci --prefer-offline

# Copy the rest of the frontend source.
COPY frontend/ ./

# Build arguments exposed to the Vite build.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

ARG APP_VERSION=dev
ENV VITE_APP_VERSION=${APP_VERSION}

# The Vite config sets outDir to ../backend/static — produce the bundle there.
RUN npm run build

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 — Python runtime
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG APP_VERSION=1.0.0
ENV APP_VERSION=${APP_VERSION}

LABEL org.opencontainers.image.title="HAMq Consumer" \
      org.opencontainers.image.description="Kafka consumer backend — FastAPI + React UI" \
      org.opencontainers.image.version="${APP_VERSION}"

# Security hardening: run as non-root user.
RUN groupadd --gid 1001 hamq && \
    useradd --uid 1001 --gid 1001 --no-create-home hamq

WORKDIR /app

# Install Python dependencies.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source.
COPY backend/ ./

# Copy the compiled React SPA from Stage 1 into the static directory that
# FastAPI's StaticFiles middleware will serve.
COPY --from=frontend-builder /app/backend/static ./static

# Create the data directory for SQLite (the PVC will be mounted here).
RUN mkdir -p /data && chown hamq:hamq /data

# Switch to non-root user.
USER hamq

# Expose the API port.
EXPOSE 8001

# Health check — Kubernetes will use the /api/health endpoint instead, but
# this gives local docker-compose a working check.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/health')" \
    || exit 1

# Start uvicorn pointing at the FastAPI app module.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
