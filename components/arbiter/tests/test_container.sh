#!/usr/bin/env bash
# =============================================================================
# HAMq Arbiter — container smoke test
# Usage: IMAGE=ghcr.io/lambdawp-567/hamq-arbiter:latest bash test_container.sh
# =============================================================================

set -euo pipefail

IMAGE="${IMAGE:-hamq-arbiter:local}"
CONTAINER_NAME="hamq-arbiter-smoke-$$"
API_PORT="18002"
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
  -p "${API_PORT}:8002" \
  -e PRODUCER_API_URLS="http://localhost:8000" \
  -e CONSUMER_API_URL="http://localhost:8001" \
  -e AUDIT_DB_PATH="/tmp/arbiter.db" \
  -e RECONCILE_INTERVAL_S="30" \
  -e RECONCILE_AUTOSTART="false" \
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
