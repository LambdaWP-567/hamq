#!/usr/bin/env bash
# =============================================================================
# HAMq Producer — container smoke test
#
# Verifies that:
#   1. The Docker image can be pulled (or built locally)
#   2. The container starts without crashing
#   3. The /api/health endpoint returns HTTP 200
#   4. The /metrics endpoint returns Prometheus text format
#   5. The container stops cleanly
#
# Usage:
#   IMAGE=ghcr.io/lambdawp-567/hamq-producer:latest bash test_container.sh
#   IMAGE=hamq-producer:local bash test_container.sh
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
IMAGE="${IMAGE:-hamq-producer:local}"
CONTAINER_NAME="hamq-producer-smoke-$$"
API_PORT="18000"          # Host port mapped to container 8000
STARTUP_TIMEOUT=30        # Seconds to wait for the container to become healthy
HEALTH_URL="http://localhost:${API_PORT}/api/health"
METRICS_URL="http://localhost:${API_PORT}/metrics"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date +%T)] $*"; }
fail() { echo "[$(date +%T)] FAIL: $*" >&2; cleanup; exit 1; }

cleanup() {
  log "Stopping container ${CONTAINER_NAME}…"
  docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  docker rm   "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# ── Test 1: Start the container ───────────────────────────────────────────────
log "Starting container from image: ${IMAGE}"
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${API_PORT}:8000" \
  -e KAFKA_BOOTSTRAP_SERVERS="localhost:9092" \
  -e KAFKA_TLS_ENABLED="false" \
  -e BUFFER_DB_PATH="/tmp/test_buffer.db" \
  -e PRODUCER_ID="smoke-test" \
  -e PRODUCER_AUTOSTART="false" \
  -e AUTH_USERNAME="admin" \
  -e AUTH_PASSWORD_HASH='$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TiGhYp.dKjQFhYVWMxJYBv9L2.Ry' \
  -e AUTH_SECRET_KEY="smoke-test-secret-key-32-chars-ok" \
  "${IMAGE}" >/dev/null

# ── Test 2: Wait for healthy status ──────────────────────────────────────────
log "Waiting for container to be healthy (timeout: ${STARTUP_TIMEOUT}s)…"
elapsed=0
while [ "${elapsed}" -lt "${STARTUP_TIMEOUT}" ]; do
  if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
    log "Container is healthy after ${elapsed}s"
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

if [ "${elapsed}" -ge "${STARTUP_TIMEOUT}" ]; then
  log "Container logs:"
  docker logs "${CONTAINER_NAME}"
  fail "Container did not become healthy within ${STARTUP_TIMEOUT}s"
fi

# ── Test 3: Health endpoint returns correct JSON ──────────────────────────────
log "Testing GET ${HEALTH_URL}…"
HEALTH_RESPONSE=$(curl -sf "${HEALTH_URL}")
echo "${HEALTH_RESPONSE}" | grep -q '"status"' \
  || fail "/api/health did not return expected JSON (got: ${HEALTH_RESPONSE})"
log "Health endpoint OK: ${HEALTH_RESPONSE}"

# ── Test 4: Metrics endpoint returns Prometheus format ────────────────────────
log "Testing GET ${METRICS_URL}…"
METRICS_RESPONSE=$(curl -sf "${METRICS_URL}")
echo "${METRICS_RESPONSE}" | grep -q '^# HELP' \
  || fail "/metrics did not return Prometheus format (got first 200 chars: ${METRICS_RESPONSE:0:200})"
log "Metrics endpoint OK"

# ── Test 5: Container process is still running ────────────────────────────────
STATUS=$(docker inspect "${CONTAINER_NAME}" --format '{{.State.Status}}')
[ "${STATUS}" = "running" ] \
  || fail "Container exited unexpectedly (status: ${STATUS})"
log "Container is running (status: ${STATUS})"

log "All smoke tests passed for image: ${IMAGE}"
