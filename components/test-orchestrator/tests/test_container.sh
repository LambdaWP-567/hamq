#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/lambdawp-567/hamq-test-orchestrator:latest}"
CONTAINER="hamq-orch-smoke-$$"

cleanup() { docker rm -f "$CONTAINER" 2>/dev/null || true; }
trap cleanup EXIT

echo "Pulling $IMAGE ..."
docker pull "$IMAGE"

echo "Starting container ..."
docker run -d \
  --name "$CONTAINER" \
  -p 18200:8000 \
  -e AUTH_USERNAME=admin \
  -e KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
  -e KAFKA_TLS_ENABLED=false \
  "$IMAGE"

echo "Waiting for health ..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:18200/api/health >/dev/null 2>&1; then
    echo "✓ Health OK"
    break
  fi
  [ $i -eq 20 ] && { echo "✗ Timeout"; exit 1; }
  sleep 2
done

echo "Checking version endpoint ..."
VERSION=$(curl -sf http://localhost:18200/api/version | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])")
echo "✓ Version: $VERSION"

echo "Smoke test passed."
