# =============================================================================
# HAMq Test Orchestrator — multi-stage image
# Stage 1: Node 20 — build React/Vite SPA
# Stage 2: Python 3.12 — FastAPI backend + SPA as static files
# Exposed port: 8000
# =============================================================================

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

# ─── Runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG APP_VERSION=1.0.0
ENV APP_VERSION=${APP_VERSION}

LABEL org.opencontainers.image.title="HAMq Test Orchestrator" \
      org.opencontainers.image.description="Counter integrity test for the HAMq databus" \
      org.opencontainers.image.version="${APP_VERSION}"

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 hamq && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false hamq

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ ./app/

COPY --from=frontend-builder /app/backend/static ./static/

USER hamq

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
