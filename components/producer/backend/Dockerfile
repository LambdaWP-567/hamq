# =============================================================================
# HAMq Producer — Multi-stage Docker build
#
# Stage 1 (frontend-builder): Build the React/Vite frontend into static files
# Stage 2 (production):       Python 3.12-slim with all dependencies + frontend
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Build the React frontend
# -----------------------------------------------------------------------------
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

# Copy package files first to leverage Docker layer caching.
# npm install only re-runs when package.json or package-lock.json changes.
COPY ../frontend/package.json ../frontend/package-lock.json* ./

# Install all dependencies (including devDependencies for the build)
RUN npm ci --prefer-offline

# Copy the rest of the frontend source
COPY ../frontend/ ./

# Build — Vite outputs to ../backend/static per vite.config.ts
# We override the outDir here to keep the build self-contained inside Stage 1.
RUN npm run build -- --outDir /dist

# -----------------------------------------------------------------------------
# Stage 2: Production Python image
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS production

# Metadata labels (OCI Image Spec)
LABEL org.opencontainers.image.title="HAMq Producer" \
      org.opencontainers.image.description="Resilient Kafka message producer with SQLite buffer" \
      org.opencontainers.image.version="1.0.0"

# Install curl for the Docker health check (minimal extra layer)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (uid=1000) to run the application.
# Running as root inside a container is a security risk and is rejected by
# many Kubernetes PodSecurityPolicies / SecurityContextConstraints.
RUN groupadd --gid 1000 hamq && \
    useradd --uid 1000 --gid 1000 --no-create-home --shell /bin/false hamq

# Application working directory
WORKDIR /app

# Install Python dependencies before copying application code so that this
# layer is cached as long as requirements.txt is unchanged.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Copy the built React frontend into the location where main.py expects it
# (./static/ relative to the backend working directory)
COPY --from=frontend-builder /dist ./static/

# Create the data directory used by the SQLite buffer.
# In production this is overridden by a Kubernetes PersistentVolume mount.
RUN mkdir -p /data && chown hamq:hamq /data

# Switch to non-root user
USER hamq

# Expose the API port
EXPOSE 8000

# Health check — Kubernetes probes also call /api/health, but having this
# here means `docker run` health monitoring works without Kubernetes.
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start the uvicorn ASGI server.
# Use --workers 1 because the in-memory ring buffer and asyncio tasks are
# not safe to share across processes.  For higher throughput, deploy multiple
# producer Pods via the Helm chart's replicaCount.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--log-level", "info"]
