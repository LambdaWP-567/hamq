#!/usr/bin/env bash
# =============================================================================
# test-api.sh — comprehensive API + WebSocket connectivity test for HAMq
#
# Tests every endpoint of every component against the running cluster,
# including auth flows, protected routes, mutation endpoints, and WebSocket.
#
# Usage:
#   bash infra/test-api.sh                    # default: *.hamq.test
#   BASE_DOMAIN=hamq.test bash infra/test-api.sh
#   BASE_URL=http://192.168.122.200 bash infra/test-api.sh   # direct
# =============================================================================

set -euo pipefail
export LANG=C LC_ALL=C

BASE_DOMAIN="${BASE_DOMAIN:-hamq.test}"
PASS=0; FAIL=0; SKIP=0

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
BLUE='\033[1;34m'; RESET='\033[0m'

log()  { printf "${BLUE}[%s]${RESET} %s\n" "$(date '+%H:%M:%S')" "$*"; }
pass() { PASS=$((PASS+1)); printf "  ${GREEN}✓ PASS${RESET}  %s\n" "$*"; }
fail() { FAIL=$((FAIL+1)); printf "  ${RED}✗ FAIL${RESET}  %s\n" "$*"; }
skip() { SKIP=$((SKIP+1)); printf "  ${YELLOW}⊘ SKIP${RESET}  %s\n" "$*"; }
section() { echo; printf "${BLUE}══════════════════════════════════════════════════════${RESET}\n"; \
            printf "${BLUE}  %s${RESET}\n" "$*"; \
            printf "${BLUE}══════════════════════════════════════════════════════${RESET}\n"; }

# ─── Helpers ──────────────────────────────────────────────────────────────────
# check_get  LABEL URL [EXPECTED_CODE] [TOKEN]
check_get() {
  local label=$1 url=$2 expected=${3:-200} token=${4:-}
  local headers=()
  [[ -n "$token" ]] && headers+=(-H "Authorization: Bearer $token")
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "${headers[@]}" "$url" 2>/dev/null)
  if [[ "$code" == "$expected" ]]; then pass "$label → $code"; else fail "$label → got $code (expected $expected)"; fi
}

# check_post LABEL URL BODY [EXPECTED_CODE] [TOKEN]
check_post() {
  local label=$1 url=$2 body=$3 expected=${4:-200} token=${5:-}
  local headers=(-H "Content-Type: application/json")
  [[ -n "$token" ]] && headers+=(-H "Authorization: Bearer $token")
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${headers[@]}" -d "$body" "$url" 2>/dev/null)
  if [[ "$code" == "$expected" ]]; then pass "$label → $code"; else fail "$label → got $code (expected $expected)"; fi
}

# check_put LABEL URL BODY [EXPECTED_CODE] [TOKEN]
check_put() {
  local label=$1 url=$2 body=$3 expected=${4:-200} token=${5:-}
  local headers=(-H "Content-Type: application/json")
  [[ -n "$token" ]] && headers+=(-H "Authorization: Bearer $token")
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "${headers[@]}" -d "$body" "$url" 2>/dev/null)
  if [[ "$code" == "$expected" ]]; then pass "$label → $code"; else fail "$label → got $code (expected $expected)"; fi
}

# check_delete LABEL URL [EXPECTED_CODE] [TOKEN]
check_delete() {
  local label=$1 url=$2 expected=${3:-200} token=${4:-}
  local headers=()
  [[ -n "$token" ]] && headers+=(-H "Authorization: Bearer $token")
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${headers[@]}" "$url" 2>/dev/null)
  if [[ "$code" == "$expected" ]]; then pass "$label → $code"; else fail "$label → got $code (expected $expected)"; fi
}

# check_ws LABEL WS_URL
check_ws() {
  local label=$1 url=$2
  # Use curl to initiate WebSocket handshake — 101 = success
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Connection: Upgrade" \
    -H "Upgrade: websocket" \
    -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
    -H "Sec-WebSocket-Version: 13" \
    "$url" 2>/dev/null)
  if [[ "$code" == "101" ]]; then pass "$label → 101 Switching Protocols"; else fail "$label → got $code (expected 101)"; fi
}

# get_token COMPONENT_URL → echoes JWT
get_token() {
  local base=$1
  curl -s -X POST "${base}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null
}

# check_json_field LABEL URL FIELD TOKEN — verifies a field exists in JSON response
check_json_field() {
  local label=$1 url=$2 field=$3 token=${4:-}
  local headers=()
  [[ -n "$token" ]] && headers+=(-H "Authorization: Bearer $token")
  local body
  body=$(curl -s "${headers[@]}" "$url" 2>/dev/null)
  if echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); assert '$field' in d" 2>/dev/null; then
    pass "$label (field '$field' present)"
  else
    fail "$label (field '$field' missing — body: ${body:0:100})"
  fi
}

# ─── Reachability pre-check ───────────────────────────────────────────────────
section "Pre-check: DNS + reachability"
for comp in producer consumer arbiter controller; do
  host="${comp}.${BASE_DOMAIN}"
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://${host}/" 2>/dev/null)
  if [[ "$code" =~ ^(200|302|401) ]]; then
    pass "${host} reachable (${code})"
  else
    fail "${host} NOT reachable (${code:-no response})"
  fi
done


# =============================================================================
# PRODUCER
# =============================================================================
section "Producer — http://producer.${BASE_DOMAIN}"
PROD="http://producer.${BASE_DOMAIN}"

log "Getting producer token..."
PROD_TOKEN=$(get_token "$PROD")
[[ -n "$PROD_TOKEN" ]] && pass "Login → token received" || { fail "Login → no token"; PROD_TOKEN=""; }

# Public endpoints
check_get  "GET  /api/health           (no auth)" "${PROD}/api/health"         200
check_get  "GET  /api/version          (no auth)" "${PROD}/api/version"        200
check_get  "GET  /metrics              (no auth)" "${PROD}/metrics"            200

# Auth
check_post "POST /api/auth/login       (valid)"   "${PROD}/api/auth/login"  '{"username":"admin","password":"admin"}' 200
check_post "POST /api/auth/login       (bad creds)" "${PROD}/api/auth/login" '{"username":"admin","password":"wrong"}' 401

# Protected — no token → 401
check_get  "GET  /api/status           (no auth → 401)" "${PROD}/api/status" 401

# Protected — with token
check_get  "GET  /api/status           (authed)"  "${PROD}/api/status"         200 "$PROD_TOKEN"
check_json_field "GET /api/status       (has kafka_connected)" "${PROD}/api/status" "kafka_connected" "$PROD_TOKEN"
check_json_field "GET /api/status       (has sent_count)"      "${PROD}/api/status" "sent_count"      "$PROD_TOKEN"

# v1 alias routes (what the React UI calls)
check_get  "GET  /api/v1/producer/status (v1 alias)" "${PROD}/api/v1/producer/status" 200 "$PROD_TOKEN"
check_post "POST /api/v1/producer/start  (v1 alias)" "${PROD}/api/v1/producer/start"  '{}' 200 "$PROD_TOKEN"
check_post "POST /api/v1/producer/stop   (v1 alias)" "${PROD}/api/v1/producer/stop"   '{}' 200 "$PROD_TOKEN"
check_put  "PUT  /api/v1/producer/frequency (v1 alias)" "${PROD}/api/v1/producer/frequency" '{"frequency_hz":2.0}' 200 "$PROD_TOKEN"

# Direct routes
check_post "POST /api/start"           "${PROD}/api/start"       '{}' 200 "$PROD_TOKEN"
check_post "POST /api/stop"            "${PROD}/api/stop"        '{}' 200 "$PROD_TOKEN"
check_put  "PUT  /api/frequency"       "${PROD}/api/frequency"   '{"frequency_hz":1.0}' 200 "$PROD_TOKEN"
check_get  "GET  /api/messages/recent" "${PROD}/api/messages/recent" 200 "$PROD_TOKEN"

# UI static files
check_get  "GET  / (React SPA)"        "${PROD}/"                200

# WebSocket
check_ws   "WS   /ws (with token)"     "http://producer.${BASE_DOMAIN}/ws?token=${PROD_TOKEN}"


# =============================================================================
# CONSUMER
# =============================================================================
section "Consumer — http://consumer.${BASE_DOMAIN}"
CONS="http://consumer.${BASE_DOMAIN}"

log "Getting consumer token..."
CONS_TOKEN=$(get_token "$CONS")
[[ -n "$CONS_TOKEN" ]] && pass "Login → token received" || { fail "Login → no token"; CONS_TOKEN=""; }

check_get  "GET  /api/health           (no auth)" "${CONS}/api/health"  200
check_get  "GET  /api/version          (no auth)" "${CONS}/api/version" 200
check_get  "GET  /metrics              (no auth)" "${CONS}/metrics"     200
check_post "POST /api/auth/login       (valid)"   "${CONS}/api/auth/login" '{"username":"admin","password":"admin"}' 200
check_post "POST /api/auth/login       (bad creds)" "${CONS}/api/auth/login" '{"username":"x","password":"x"}' 401
check_get  "GET  /api/status           (no auth → 403)" "${CONS}/api/status" 403
check_get  "GET  /api/status           (authed)"  "${CONS}/api/status"  200 "$CONS_TOKEN"
check_json_field "GET /api/status       (has kafka_connected)" "${CONS}/api/status" "kafka_connected" "$CONS_TOKEN"
check_json_field "GET /api/status       (has received_count)"  "${CONS}/api/status" "received_count"  "$CONS_TOKEN"
check_post "POST /api/start"           "${CONS}/api/start"    '{}' 200 "$CONS_TOKEN"
check_get  "GET  /api/messages/recent" "${CONS}/api/messages/recent" 200 "$CONS_TOKEN"
check_get  "GET  /api/messages/missing (with params)" "${CONS}/api/messages/missing?producer_id=test&seq_from=1&seq_to=10" 200 "$CONS_TOKEN"
check_get  "GET  /api/messages/missing (no params → 422)" "${CONS}/api/messages/missing" 422 "$CONS_TOKEN"
check_get  "GET  / (React SPA)"        "${CONS}/"             200
check_ws   "WS   /ws (with token)"     "http://consumer.${BASE_DOMAIN}/ws?token=${CONS_TOKEN}"


# =============================================================================
# ARBITER
# =============================================================================
section "Arbiter — http://arbiter.${BASE_DOMAIN}"
ARB="http://arbiter.${BASE_DOMAIN}"

log "Getting arbiter token..."
ARB_TOKEN=$(get_token "$ARB")
[[ -n "$ARB_TOKEN" ]] && pass "Login → token received" || { fail "Login → no token"; ARB_TOKEN=""; }

check_get  "GET  /api/health           (no auth)" "${ARB}/api/health"  200
check_get  "GET  /api/version          (no auth)" "${ARB}/api/version" 200
check_get  "GET  /metrics              (no auth)" "${ARB}/metrics"     200
check_post "POST /api/auth/login       (valid)"   "${ARB}/api/auth/login" '{"username":"admin","password":"admin"}' 200
check_post "POST /api/auth/login       (bad creds)" "${ARB}/api/auth/login" '{"username":"x","password":"x"}' 401
check_get  "GET  /api/status           (no auth → 401)" "${ARB}/api/status" 401
check_get  "GET  /api/status           (authed)"  "${ARB}/api/status"  200 "$ARB_TOKEN"
check_json_field "GET /api/status       (has running)"  "${ARB}/api/status" "running" "$ARB_TOKEN"
check_post "POST /api/start"           "${ARB}/api/start"     '{}' 200 "$ARB_TOKEN"
check_get  "GET  /api/stats"           "${ARB}/api/stats"     200 "$ARB_TOKEN"
check_get  "GET  /api/audits"          "${ARB}/api/audits"    200 "$ARB_TOKEN"
check_post "POST /api/reconcile"       "${ARB}/api/reconcile" '{}' 200 "$ARB_TOKEN"
check_get  "GET  / (React SPA)"        "${ARB}/"              200
check_ws   "WS   /ws (with token)"     "http://arbiter.${BASE_DOMAIN}/ws?token=${ARB_TOKEN}"


# =============================================================================
# CONTROLLER
# =============================================================================
section "Controller — http://controller.${BASE_DOMAIN}"
CTRL="http://controller.${BASE_DOMAIN}"

log "Getting controller token..."
CTRL_TOKEN=$(get_token "$CTRL")
[[ -n "$CTRL_TOKEN" ]] && pass "Login → token received" || { fail "Login → no token"; CTRL_TOKEN=""; }

check_get  "GET  /api/health           (no auth)" "${CTRL}/api/health"  200
check_get  "GET  /api/version          (no auth)" "${CTRL}/api/version" 200
check_get  "GET  /metrics              (no auth)" "${CTRL}/metrics"     200
check_post "POST /api/auth/login       (valid)"   "${CTRL}/api/auth/login" '{"username":"admin","password":"admin"}' 200
check_post "POST /api/auth/login       (bad creds)" "${CTRL}/api/auth/login" '{"username":"x","password":"x"}' 401
check_get  "GET  /api/status           (no auth → 401)" "${CTRL}/api/status" 401
check_get  "GET  /api/status           (authed)"  "${CTRL}/api/status"  200 "$CTRL_TOKEN"
check_json_field "GET /api/status       (has k8s_connected)" "${CTRL}/api/status" "k8s_connected" "$CTRL_TOKEN"
check_get  "GET  /api/pods"            "${CTRL}/api/pods"           200 "$CTRL_TOKEN"
check_get  "GET  /api/nodes"           "${CTRL}/api/nodes"          200 "$CTRL_TOKEN"
check_get  "GET  /api/network-policies" "${CTRL}/api/network-policies" 200 "$CTRL_TOKEN"
check_get  "GET  /api/chaos/status"    "${CTRL}/api/chaos/status"   200 "$CTRL_TOKEN"
check_get  "GET  /api/events"          "${CTRL}/api/events"         200 "$CTRL_TOKEN"
check_get  "GET  / (React SPA)"        "${CTRL}/"                   200
check_ws   "WS   /ws (with token)"     "http://controller.${BASE_DOMAIN}/ws?token=${CTRL_TOKEN}"


# =============================================================================
# SUMMARY
# =============================================================================
TOTAL=$((PASS + FAIL + SKIP))
echo
printf "${BLUE}══════════════════════════════════════════════════════${RESET}\n"
printf "${BLUE}  Results: %d total  ${GREEN}%d passed${BLUE}  ${RED}%d failed${BLUE}  ${YELLOW}%d skipped${RESET}\n" \
  "$TOTAL" "$PASS" "$FAIL" "$SKIP"
printf "${BLUE}══════════════════════════════════════════════════════${RESET}\n"
echo

[[ $FAIL -eq 0 ]] && { echo "All tests passed ✓"; exit 0; } || { echo "Some tests FAILED ✗"; exit 1; }
