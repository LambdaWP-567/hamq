# ---------------------------------------------------------------------------
# HAMq Arbiter — Multi-stage Dockerfile
# ---------------------------------------------------------------------------
# Stage 1 (builder): Install Python dependencies into a virtualenv so that
#   only the venv (no pip caches or build tools) is copied to the final image.
# Stage 2 (runtime): Minimal Python image with the app code and venv only.
#
# The final image runs as a non-root user (uid 1000) for Kubernetes Pod
# Security Standards compliance.
# ---------------------------------------------------------------------------

# ---- Stage 1: dependency builder ----------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# System packages needed only at build time (for bcrypt's C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to maximise Docker layer caching — if
# requirements.txt hasn't changed, all subsequent layers are cache-hits.
COPY requirements.txt .

# Create an isolated virtualenv and install all Python dependencies.
# --no-cache-dir keeps the image smaller; --upgrade ensures latest pip.
RUN python -m venv /venv && \
    /venv/bin/pip install --upgrade pip --no-cache-dir && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt


# ---- Stage 2: runtime image ----------------------------------------------
FROM python:3.12-slim AS runtime

# Metadata labels (OCI standard)
LABEL org.opencontainers.image.title="HAMq Arbiter"
LABEL org.opencontainers.image.description="Message-loss arbiter for the HAMq system"
LABEL org.opencontainers.image.version="1.0.0"

WORKDIR /app

# Copy the pre-built virtualenv from the builder stage
COPY --from=builder /venv /venv

# Copy application source code
COPY app/ ./app/

# Create the data directory that SQLite will write into.
# In Kubernetes this path is overlaid by a PersistentVolumeClaim mount.
RUN mkdir -p /data && chmod 777 /data

# Create a non-root user and group (uid/gid 1000)
RUN groupadd --gid 1000 arbiter && \
    useradd  --uid 1000 --gid arbiter --no-create-home arbiter

# Ensure the app directory and venv are owned by the non-root user
RUN chown -R arbiter:arbiter /app /venv /data

USER arbiter

# Activate the virtualenv for all subsequent RUN / CMD instructions
ENV PATH="/venv/bin:$PATH"

# Expose the Arbiter API port (must match API_PORT env var)
EXPOSE 8002

# Health check — Kubernetes also uses liveness/readiness probes, but
# this HEALTHCHECK is useful for docker compose and local testing.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/api/health')" \
    || exit 1

# Start uvicorn with:
#   --host 0.0.0.0   → listen on all interfaces (required in containers)
#   --port 8002      → matches the exposed port and API_PORT default
#   --workers 1      → single worker; state is in SQLite/asyncio, not shared memory
#   --no-access-log  → access logs are noisy; use Kubernetes log aggregation instead
CMD ["/venv/bin/uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8002", \
     "--workers", "1"]
