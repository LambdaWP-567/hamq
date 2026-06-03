#!/usr/bin/env bash
# =============================================================================
# HAMq Consumer — container smoke test
# Verifies the container starts and exposes healthy /api/health and /metrics.
# Usage: IMAGE=ghcr.io/lambdawp-567/hamq-consumer:latest bash test_container.sh
# =============================================================================

set -euo pipefail

IMAGE="${IMAGE:-hamq-consumer:local}"
CONTAINER_NAME="hamq-consumer-smoke-$$"
API_PORT="18001"
STARTUP_TIMEOUT=30
HEALTH_URL="http://localhost:${API_PORT}/api/health"
METRICS_URL="http://localhost:${API_PORT}/metrics"

log()  { echo "[$(date +%T)] $*"; }
fail() { echo "[$(date +%T)] FAIL: $*" >&2; cleanup; exit 1; }

cleanup() {
  docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  docker rm   "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "Starting container from image: ${IMAGE}"
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${API_PORT}:8001" \
  -e KAFKA_BOOTSTRAP_SERVERS="localhost:9092" \
  -e KAFKA_TLS_ENABLED="false" \
  -e STORAGE_DB_PATH="/tmp/consumer.db" \
  -e CONSUMER_GROUP_ID="smoke-test-group" \
  -e AUTH_USERNAME="admin" \
  -e AUTH_PASSWORD_HASH='$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGhYp.dKjQFhYVWMxJYBv9L2.Ry' \
  -e AUTH_SECRET_KEY="smoke-test-secret-key-32-chars-ok" \
  "${IMAGE}" >/dev/null

log "Waiting for healthy status (timeout: ${STARTUP_TIMEOUT}s)…"
elapsed=0
while [ "${elapsed}" -lt "${STARTUP_TIMEOUT}" ]; do
  if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
    log "Healthy after ${elapsed}s"; break
  fi
  sleep 2; elapsed=$((elapsed + 2))
done
[ "${elapsed}" -lt "${STARTUP_TIMEOUT}" ] || { docker logs "${CONTAINER_NAME}"; fail "Startup timeout"; }

log "Testing /api/health…"
curl -sf "${HEALTH_URL}" | grep -q '"status"' || fail "Unexpected health response"

log "Testing /metrics…"
curl -sf "${METRICS_URL}" | grep -q '^# HELP' || fail "Metrics not in Prometheus format"

STATUS=$(docker inspect "${CONTAINER_NAME}" --format '{{.State.Status}}')
[ "${STATUS}" = "running" ] || fail "Container exited (status: ${STATUS})"

log "All smoke tests passed for image: ${IMAGE}"
