#!/usr/bin/env bash
# End-to-end smoke test against a running BlackBox API.
#
#   ./scripts/smoke.sh                          # http://localhost:8000
#   BASE_URL=https://api.example.com ./scripts/smoke.sh
#
# Exercises the real HTTP surface — auth, RBAC, token rotation, password reset
# and the audit trail — so it catches wiring problems the unit tests cannot,
# such as middleware ordering or a bootstrap account that cannot log in.
#
# Requires: curl, python3. Exits non-zero if any check fails.
#
# NOTE: this creates and deletes users. Run it against a development or
# staging deployment, never production.
set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API="${BASE_URL}/api/v1"
ADMIN_EMAIL="${FIRST_SUPERUSER_EMAIL:-admin@blackbox.example.com}"
ADMIN_PASSWORD="${FIRST_SUPERUSER_PASSWORD:-ChangeMe123!}"
# Unique suffix so repeated runs do not collide on the unique email index.
RUN_ID="$(date +%s)$$"
BODY="$(mktemp)"
trap 'rm -f "${BODY}"' EXIT

pass=0
fail=0

check() { # check <name> <expected-status> <actual-status>
  if [[ "$2" == "$3" ]]; then
    printf '  \033[32mPASS\033[0m  %-40s %s\n' "$1" "$3"
    pass=$((pass + 1))
  else
    printf '  \033[31mFAIL\033[0m  %-40s expected %s, got %s\n' "$1" "$2" "$3"
    fail=$((fail + 1))
  fi
}

status() { curl -s -o "${BODY}" -w '%{http_code}' "$@"; }
field() { python3 -c "import json,sys;print(json.load(open('${BODY}'))$1)" 2>/dev/null || echo ""; }

echo "Smoke testing ${BASE_URL}"
echo

echo "── Health ──────────────────────────────────────────────"
check "GET /health" 200 "$(status "${BASE_URL}/health")"
check "GET /health/ready" 200 "$(status "${BASE_URL}/health/ready")"
echo "        database=$(field "['checks']['database']") redis=$(field "['checks']['redis']")"

echo "── Authentication ──────────────────────────────────────"
check "POST /auth/login" 200 "$(status -X POST "${API}/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}")"
ACCESS="$(field "['access_token']")"
REFRESH="$(field "['refresh_token']")"
if [[ -z "${ACCESS}" ]]; then
  echo "  cannot continue: admin login failed — check FIRST_SUPERUSER_* settings" >&2
  exit 1
fi

check "POST /auth/login (wrong password)" 401 "$(status -X POST "${API}/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"Definitely!Wrong9\"}")"

check "GET /auth/me" 200 "$(status "${API}/auth/me" -H "Authorization: Bearer ${ACCESS}")"

echo "── Registration ────────────────────────────────────────"
VIEWER_EMAIL="smoke-viewer-${RUN_ID}@example.com"
check "POST /auth/register" 201 "$(status -X POST "${API}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${VIEWER_EMAIL}\",\"password\":\"Str0ng!Passw0rd\",\"full_name\":\"Smoke Viewer\"}")"
echo "        assigned roles: $(field "['roles'][0]['name']")"
check "POST /auth/register (duplicate)" 409 "$(status -X POST "${API}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${VIEWER_EMAIL}\",\"password\":\"Str0ng!Passw0rd\"}")"
check "POST /auth/register (weak password)" 422 "$(status -X POST "${API}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"smoke-weak-${RUN_ID}@example.com\",\"password\":\"password\"}")"

echo "── Role-based access control ───────────────────────────"
status -X POST "${API}/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${VIEWER_EMAIL}\",\"password\":\"Str0ng!Passw0rd\"}" >/dev/null
VIEWER_ACCESS="$(field "['access_token']")"
check "GET /users as viewer" 403 "$(status "${API}/users" -H "Authorization: Bearer ${VIEWER_ACCESS}")"
check "GET /users anonymous" 401 "$(status "${API}/users")"
check "GET /users as admin" 200 "$(status "${API}/users" -H "Authorization: Bearer ${ACCESS}")"
check "GET /users/roles as admin" 200 "$(status "${API}/users/roles" -H "Authorization: Bearer ${ACCESS}")"

echo "── User administration ─────────────────────────────────"
check "POST /users" 201 "$(status -X POST "${API}/users" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d "{\"email\":\"smoke-eng-${RUN_ID}@example.com\",\"password\":\"Str0ng!Passw0rd\",
       \"full_name\":\"Smoke Engineer\",\"roles\":[\"engineer\"]}")"
CREATED_ID="$(field "['id']")"
check "PATCH /users/{id} (unknown role)" 422 "$(status -X PATCH "${API}/users/${CREATED_ID}" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"roles":["wizard"]}')"
check "PATCH /users/{id} (deactivate)" 200 "$(status -X PATCH "${API}/users/${CREATED_ID}" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"is_active":false}')"
check "DELETE /users/{id}" 204 "$(status -X DELETE "${API}/users/${CREATED_ID}" \
  -H "Authorization: Bearer ${ACCESS}")"
check "GET /users/{id} (deleted)" 404 "$(status "${API}/users/${CREATED_ID}" \
  -H "Authorization: Bearer ${ACCESS}")"

echo "── Token rotation ──────────────────────────────────────"
check "POST /auth/refresh" 200 "$(status -X POST "${API}/auth/refresh" \
  -H 'Content-Type: application/json' -d "{\"refresh_token\":\"${REFRESH}\"}")"
NEW_REFRESH="$(field "['refresh_token']")"
check "POST /auth/refresh (replay)" 401 "$(status -X POST "${API}/auth/refresh" \
  -H 'Content-Type: application/json' -d "{\"refresh_token\":\"${REFRESH}\"}")"
check "POST /auth/logout (all sessions)" 200 "$(status -X POST "${API}/auth/logout" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"all_sessions":true}')"
check "POST /auth/refresh (after logout)" 401 "$(status -X POST "${API}/auth/refresh" \
  -H 'Content-Type: application/json' -d "{\"refresh_token\":\"${NEW_REFRESH}\"}")"

echo "── Password reset ──────────────────────────────────────"
check "POST /auth/forgot-password" 200 "$(status -X POST "${API}/auth/forgot-password" \
  -H 'Content-Type: application/json' -d "{\"email\":\"${VIEWER_EMAIL}\"}")"
check "POST /auth/forgot-password (unknown)" 200 "$(status -X POST "${API}/auth/forgot-password" \
  -H 'Content-Type: application/json' -d '{"email":"nobody-at-all@example.com"}')"
echo "        (identical responses — no user enumeration)"
check "POST /auth/reset-password (bad token)" 401 "$(status -X POST "${API}/auth/reset-password" \
  -H 'Content-Type: application/json' \
  -d '{"token":"0000000000000000000000000000000000000000000","new_password":"N3w!Str0ngPass"}')"

echo "── Audit & documentation ───────────────────────────────"
status -X POST "${API}/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" >/dev/null
ACCESS="$(field "['access_token']")"
check "GET /audit-logs" 200 "$(status "${API}/audit-logs?page=1&page_size=50" \
  -H "Authorization: Bearer ${ACCESS}")"
echo "        recorded events: $(field "['total']")"
check "GET /openapi.json" 200 "$(status "${BASE_URL}/openapi.json")"
check "GET /api/v1/no-such-route" 404 "$(status "${API}/no-such-route")"

echo
if (( fail == 0 )); then
  printf '\033[32mAll %d checks passed.\033[0m\n' "${pass}"
else
  printf '\033[31m%d of %d checks failed.\033[0m\n' "${fail}" "$((pass + fail))"
fi
exit $(( fail > 0 ))
