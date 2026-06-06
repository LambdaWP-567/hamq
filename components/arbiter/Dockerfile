# =============================================================================
# HAMq Arbiter — combined multi-stage image (build context: components/arbiter/)
#
# Stage 1 : Node 20 — build the React/Vite SPA
# Stage 2 : Python 3.12 — FastAPI backend + SPA served as static files
#
# Exposed port: 8002
# =============================================================================

# ─── Stage 1: React frontend ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ ./

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

ARG APP_VERSION=dev
ENV VITE_APP_VERSION=${APP_VERSION}

RUN npm run build

# ─── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG APP_VERSION=1.0.0
ENV APP_VERSION=${APP_VERSION}

LABEL org.opencontainers.image.title="HAMq Arbiter" \
      org.opencontainers.image.description="Message-loss detection arbiter — FastAPI + React UI" \
      org.opencontainers.image.version="${APP_VERSION}"

RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 hamq && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false hamq

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/

# React SPA served as static files by FastAPI
COPY --from=frontend-builder /app/frontend/dist ./static/

RUN mkdir -p /data && chown hamq:hamq /data

USER hamq

EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/api/health')" \
    || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
