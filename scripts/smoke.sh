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

echo "── Devices ─────────────────────────────────────────────"
DEVICE_ID="STM32-SMOKE-${RUN_ID: -6}"
# @name createDevice
check "POST /devices" 201 "$(status -X POST "${API}/devices" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d "{\"device_id\":\"${DEVICE_ID}\",\"serial_number\":\"SN-${RUN_ID: -8}\",
       \"firmware_version\":\"1.4.2\",\"hardware_model\":\"STM32F407VG\",
       \"location\":\"Smoke Lab\",\"tags\":[\"smoke-test\"]}")"
DEVICE_UUID="$(field "['id']")"
echo "        registered ${DEVICE_ID}"

check "GET /devices" 200 "$(status "${API}/devices" -H "Authorization: Bearer ${ACCESS}")"
check "GET /devices?tag=smoke-test" 200 "$(status "${API}/devices?tag=smoke-test" \
  -H "Authorization: Bearer ${ACCESS}")"
check "GET /devices as viewer (read-only ok)" 200 "$(status "${API}/devices" \
  -H "Authorization: Bearer ${VIEWER_ACCESS}")"
check "POST /devices as viewer" 403 "$(status -X POST "${API}/devices" \
  -H "Authorization: Bearer ${VIEWER_ACCESS}" -H 'Content-Type: application/json' \
  -d '{"device_id":"NOPE-1","serial_number":"SN-NOPE-1",
       "firmware_version":"1.0.0","hardware_model":"X"}')"
check "PATCH /devices/{id}" 200 "$(status -X PATCH "${API}/devices/${DEVICE_UUID}" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"firmware_version":"1.5.0"}')"

echo "── Device API keys ─────────────────────────────────────"
check "POST /devices/{id}/api-keys" 201 "$(status -X POST "${API}/devices/${DEVICE_UUID}/api-keys" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"name":"smoke-key"}')"
DEVICE_KEY="$(field "['api_key']")"
KEY_ID="$(field "['id']")"
echo "        issued key ${DEVICE_KEY:0:16}..."
check "POST /devices/heartbeat (device key)" 200 "$(status -X POST "${API}/devices/heartbeat" \
  -H "X-API-Key: ${DEVICE_KEY}" -H 'Content-Type: application/json' -d '{}')"
check "POST /devices/heartbeat (bad key)" 401 "$(status -X POST "${API}/devices/heartbeat" \
  -H 'X-API-Key: bbx_deadbeefcafe_nope')"

echo "── Crash ingestion ─────────────────────────────────────"
check "POST /crashes (device key)" 201 "$(status -X POST "${API}/crashes" \
  -H "X-API-Key: ${DEVICE_KEY}" -H 'Content-Type: application/json' \
  -d '{"firmware_version":"1.5.0","build_version":"a1b2c3d",
       "fault_type":"HardFault","task_name":"SensorTask",
       "pc":"0x08001A2C","lr":"0x08001A0F","sp":"0x20017FA0",
       "registers":{"r0":"0x00000000","r1":"0x20000100","xpsr":"0x61000000"},
       "stack":["0x08001A2C","0x20017FB0"]}')"
CRASH_ID="$(field "['id']")"
echo "        fault=$(field "['fault_type']") severity=$(field "['severity']")"

check "POST /crashes (camelCase firmware)" 201 "$(status -X POST "${API}/crashes" \
  -H "X-API-Key: ${DEVICE_KEY}" -H 'Content-Type: application/json' \
  -d '{"firmwareVersion":"1.5.0","faultType":"busFault",
       "taskName":"CommsTask","programCounter":"0x08002000"}')"
echo "        normalised to $(field "['fault_type']")"

check "POST /crashes (unparsable, still stored)" 201 "$(status -X POST "${API}/crashes" \
  -H "X-API-Key: ${DEVICE_KEY}" -H 'Content-Type: application/json' \
  -d '{"firmware_version":"1.5.0","fault_type":"???","timestamp":"whenever","pc":"junk"}')"
echo "        warnings: $(field "['warnings']")"

check "POST /crashes (no fault evidence)" 422 "$(status -X POST "${API}/crashes" \
  -H "X-API-Key: ${DEVICE_KEY}" -H 'Content-Type: application/json' \
  -d '{"firmware_version":"1.5.0"}')"
check "POST /crashes (anonymous)" 401 "$(status -X POST "${API}/crashes" \
  -H 'Content-Type: application/json' -d '{"firmware_version":"1.0.0","fault_type":"HardFault"}')"
check "POST /crashes (unknown device)" 404 "$(status -X POST "${API}/crashes" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"device_id":"NEVER-REGISTERED","firmware_version":"1.0.0","fault_type":"HardFault"}')"

echo "── Crash history & triage ──────────────────────────────"
check "GET /crashes" 200 "$(status "${API}/crashes" -H "Authorization: Bearer ${ACCESS}")"
echo "        stored crashes: $(field "['total']")"
check "GET /crashes?fault_type=hard_fault" 200 "$(status "${API}/crashes?fault_type=hard_fault" \
  -H "Authorization: Bearer ${ACCESS}")"
check "GET /crashes?device={id}" 200 "$(status "${API}/crashes?device=${DEVICE_ID}" \
  -H "Authorization: Bearer ${ACCESS}")"
check "GET /crashes/{id}" 200 "$(status "${API}/crashes/${CRASH_ID}" \
  -H "Authorization: Bearer ${ACCESS}")"
echo "        pc=$(field "['program_counter']") psr=$(field "['register_dump']['psr']")"
check "PATCH /crashes/{id} (triage)" 200 "$(status -X PATCH "${API}/crashes/${CRASH_ID}" \
  -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
  -d '{"status":"investigating","notes":"smoke test"}')"
check "PATCH /crashes/{id} as viewer" 403 "$(status -X PATCH "${API}/crashes/${CRASH_ID}" \
  -H "Authorization: Bearer ${VIEWER_ACCESS}" -H 'Content-Type: application/json' \
  -d '{"status":"resolved"}')"
check "GET /devices/{id}/stats" 200 "$(status "${API}/devices/${DEVICE_UUID}/stats" \
  -H "Authorization: Bearer ${ACCESS}")"
echo "        total=$(field "['total_crashes']") open=$(field "['open_crashes']")"

echo "── Crash analysis (Phase 2.5) ──────────────────────────"
# Symbolization needs a build artifact. Compile a tiny ELF so the check
# exercises the real pyelftools + DWARF path; skip if no compiler is present.
CC="$(command -v gcc || command -v cc || true)"
if [[ -n "${CC}" ]]; then
  ELF_DIR="$(mktemp -d)"
  cat > "${ELF_DIR}/fw.c" <<'CSRC'
volatile int sink;
int helper_add(int a, int b) { return a + b; }
void sensor_task_body(void) { sink = helper_add(sink, 3); }
int main(void) { sensor_task_body(); return sink; }
CSRC
  if "${CC}" -g -O0 -o "${ELF_DIR}/fw.elf" "${ELF_DIR}/fw.c" 2>/dev/null; then
    # Address of helper_add+4, read straight from the compiled ELF.
    PC_HEX="$(python3 - "${ELF_DIR}/fw.elf" <<'PYADDR'
import sys, subprocess, re
out = subprocess.run(["nm", sys.argv[1]], capture_output=True, text=True).stdout
for line in out.splitlines():
    parts = line.split()
    if len(parts) == 3 and parts[2] == "helper_add":
        print(hex(int(parts[0], 16) + 4)); break
PYADDR
)"
    ANALYSIS_FW="analysis-${RUN_ID: -6}"
    curl -s -X POST "${API}/devices" -H "Authorization: Bearer ${ACCESS}" \
      -H 'Content-Type: application/json' \
      -d "{\"device_id\":\"SYM-${RUN_ID: -6}\",\"serial_number\":\"SNSYM-${RUN_ID: -6}\",
           \"firmware_version\":\"${ANALYSIS_FW}\",\"hardware_model\":\"STM32F407VG\"}" \
      -o "${BODY}" >/dev/null
    SYM_DEVICE="$(field "['id']")"
    curl -s -X POST "${API}/devices/${SYM_DEVICE}/api-keys" \
      -H "Authorization: Bearer ${ACCESS}" -H 'Content-Type: application/json' \
      -d '{"name":"sym"}' -o "${BODY}" >/dev/null
    SYM_KEY="$(field "['api_key']")"

    check "POST /builds (upload ELF)" 201 "$(status -X POST "${API}/builds" \
      -H "Authorization: Bearer ${ACCESS}" \
      -F "firmware_version=${ANALYSIS_FW}" \
      -F "file=@${ELF_DIR}/fw.elf;filename=fw.elf")"
    echo "        indexed $(field "['symbol_count']") symbols, dwarf=$(field "['has_debug_info']")"

    if [[ -n "${PC_HEX}" ]]; then
      check "POST /crashes (into helper_add)" 201 "$(status -X POST "${API}/crashes" \
        -H "X-API-Key: ${SYM_KEY}" -H 'Content-Type: application/json' \
        -d "{\"firmware_version\":\"${ANALYSIS_FW}\",\"fault_type\":\"HardFault\",
             \"task_name\":\"SensorTask\",\"pc\":\"${PC_HEX}\"}")"
      SYM_CRASH="$(field "['id']")"
      check "GET /crashes/{id} (symbolized)" 200 "$(status "${API}/crashes/${SYM_CRASH}" \
        -H "Authorization: Bearer ${ACCESS}")"
      echo "        top_function=$(field "['top_function']") pc=$(field "['symbolication']['pc']['display']")"

      check "GET /crash-groups" 200 "$(status "${API}/crash-groups" \
        -H "Authorization: Bearer ${ACCESS}")"
      echo "        groups=$(field "['total']") title=$(field "['items'][0]['title']")"
      check "GET /crash-groups/top" 200 "$(status "${API}/crash-groups/top?limit=5" \
        -H "Authorization: Bearer ${ACCESS}")"
    fi
    rm -rf "${ELF_DIR}"
  else
    echo "  SKIP  crash analysis (could not compile the ELF fixture)"
    rm -rf "${ELF_DIR}"
  fi
else
  echo "  SKIP  crash analysis (no C compiler on PATH)"
fi

echo "── Cleanup ─────────────────────────────────────────────"
check "DELETE api-key" 204 "$(status -X DELETE "${API}/devices/${DEVICE_UUID}/api-keys/${KEY_ID}" \
  -H "Authorization: Bearer ${ACCESS}")"
check "POST /crashes (revoked key)" 401 "$(status -X POST "${API}/crashes" \
  -H "X-API-Key: ${DEVICE_KEY}" -H 'Content-Type: application/json' \
  -d '{"firmware_version":"1.5.0","fault_type":"HardFault"}')"
check "DELETE /devices/{id}" 204 "$(status -X DELETE "${API}/devices/${DEVICE_UUID}" \
  -H "Authorization: Bearer ${ACCESS}")"
check "GET /crashes/{id} (cascaded)" 404 "$(status "${API}/crashes/${CRASH_ID}" \
  -H "Authorization: Bearer ${ACCESS}")"

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
