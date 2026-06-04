# =============================================================================
# HAMq Consumer — backend-only image (build context: components/consumer/backend/)
#
# Used when deploying backend and frontend as separate containers (sidecar pattern).
# For the combined image (backend + SPA), use components/consumer/Dockerfile.
#
# Exposed port: 8001
# =============================================================================

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="HAMq Consumer (backend)" \
      org.opencontainers.image.description="Kafka consumer backend — FastAPI API only" \
      org.opencontainers.image.version="1.0.0"

# Non-root user for Kubernetes PodSecurityStandards compliance
RUN groupadd --gid 1001 hamq && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false hamq

WORKDIR /app

# Install dependencies before copying source (maximises layer cache hits)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# PVC will be mounted here at /data in Kubernetes
RUN mkdir -p /data && chown hamq:hamq /data

USER hamq

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/health')" \
    || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
