# Sample API requests (curl)

Every example assumes the stack is running on `http://localhost:8000`.
Interactive documentation is at <http://localhost:8000/docs>.

All error responses share one envelope:

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Incorrect email or password.",
    "details": { "...": "optional" }
  }
}
```

---

## 1. Health

```bash
curl -s http://localhost:8000/health | jq
# {"status":"ok","version":"0.1.0","environment":"local"}

curl -s http://localhost:8000/health/ready | jq
# {"status":"ok","version":"0.1.0","environment":"local",
#  "checks":{"database":"ok","redis":"ok"}}
```

`/health` never touches a dependency, so use it as the container liveness
probe. `/health/ready` returns **503** when PostgreSQL is unreachable; a Redis
outage is reported as `degraded` but still returns 200 because the API can
serve traffic without it.

---

## 2. Register

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{
        "email": "engineer@example.com",
        "password": "Str0ng!Passw0rd",
        "full_name": "Field Engineer"
      }' | jq
```

```json
{
  "id": "9f2c...",
  "email": "engineer@example.com",
  "full_name": "Field Engineer",
  "is_active": true,
  "is_verified": false,
  "roles": [{ "id": "...", "name": "viewer", "description": "..." }]
}
```

New accounts always get `viewer`. An admin grants higher roles afterwards.

Password policy: at least `PASSWORD_MIN_LENGTH` (default 10) characters with an
uppercase letter, a lowercase letter, a digit and a special character.

---

## 3. Log in

```bash
TOKENS=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@blackbox.example.com","password":"ChangeMe123!"}')

ACCESS=$(echo "$TOKENS"  | jq -r .access_token)
REFRESH=$(echo "$TOKENS" | jq -r .refresh_token)
```

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": { "email": "admin@blackbox.example.com", "roles": [{ "name": "admin" }] }
}
```

After `MAX_FAILED_LOGIN_ATTEMPTS` consecutive failures the account is locked
for `ACCOUNT_LOCKOUT_MINUTES` and login returns **423**.

---

## 4. Authenticated requests

```bash
curl -s http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $ACCESS" | jq
```

---

## 5. Rotate tokens

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}" | jq
```

Refresh tokens are **single use**: the presented token is revoked and a new
pair is issued. Replaying an old token returns **401** — which is also how
token theft surfaces.

---

## 6. Log out

```bash
# This session only
curl -s -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}" | jq

# Every session on every device
curl -s -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"all_sessions": true}' | jq
```

---

## 7. Password reset

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/forgot-password \
  -H 'Content-Type: application/json' \
  -d '{"email":"engineer@example.com"}' | jq
# {"message":"If an account exists for that email, a reset link has been sent."}
```

The response is identical whether or not the account exists, so the endpoint
cannot be used to enumerate users. With `EMAIL_BACKEND=console` the link is
printed to the backend log:

```bash
docker compose logs backend | grep reset-password
# .../reset-password?token=Q1p4...
```

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/reset-password \
  -H 'Content-Type: application/json' \
  -d '{"token":"Q1p4...","new_password":"N3w!Str0ngPass"}' | jq
```

The token is single use, expires after `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`,
and completing a reset revokes every existing session.

---

## 8. User administration (admin only)

```bash
# List, search and filter
curl -s "http://localhost:8000/api/v1/users?page=1&page_size=20" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/users?q=engineer&role=engineer&is_active=true" -H "Authorization: Bearer $ACCESS" | jq

# Create
curl -s -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"email":"engineer2@example.com","password":"Str0ng!Passw0rd",
       "full_name":"Engineer Two","roles":["engineer"]}' | jq

# Promote
curl -s -X PATCH "http://localhost:8000/api/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"roles":["engineer"]}' | jq

# Deactivate (revokes the user's sessions immediately)
curl -s -X PATCH "http://localhost:8000/api/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"is_active":false}' | jq

# Delete
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
  "http://localhost:8000/api/v1/users/$USER_ID" -H "Authorization: Bearer $ACCESS"
# 204
```

Paginated responses look like:

```json
{ "items": [ ... ], "total": 42, "page": 1, "page_size": 20, "pages": 3 }
```

A `viewer` or `engineer` calling these endpoints gets **403**:

```json
{ "error": { "code": "permission_denied",
             "message": "This action requires one of the following roles: admin",
             "details": { "required_roles": ["admin"] } } }
```

---

## 9. Self-service profile

```bash
curl -s -X PATCH http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"full_name":"Platform Administrator"}' | jq
```

A `roles` field in this payload is ignored — privilege escalation is not
possible through the self-service route.

---

## 10. Audit trail (admin only)

```bash
curl -s "http://localhost:8000/api/v1/audit-logs?action=user.login_failed" \
  -H "Authorization: Bearer $ACCESS" | jq '.items[0]'
```

```json
{
  "action": "user.login_failed",
  "actor_email": "engineer@example.com",
  "ip_address": "172.18.0.1",
  "success": false,
  "context": { "reason": "bad_password" },
  "created_at": "2026-07-27T09:14:22Z"
}
```

---

# Phase 2 — Devices & Crash Reports

## 11. Register a device

```bash
curl -s -X POST http://localhost:8000/api/v1/devices \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{
        "device_id": "STM32-F4-0001",
        "serial_number": "SN-2026-000123",
        "firmware_version": "1.4.2",
        "hardware_model": "STM32F407VG",
        "location": "Lab A, Rack 3",
        "tags": ["field-trial", "eu-west"]
      }' | jq
```

Requires `engineer`. `device_id` and `serial_number` are unique and immutable —
every crash the device has ever sent references them, so a rename would rewrite
history. Tags are normalised to lower case and de-duplicated.

## 12. Search the fleet

```bash
curl -s "http://localhost:8000/api/v1/devices?q=rack%203" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/devices?status=active&hardware_model=STM32F407VG" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/devices?tag=field-trial" -H "Authorization: Bearer $ACCESS" | jq

# Devices seen in the last 24 hours. Note the %2B: a raw "+" in a query
# string decodes as a space.
SINCE=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
curl -s "http://localhost:8000/api/v1/devices?online_since=$SINCE" -H "Authorization: Bearer $ACCESS" | jq
```

## 13. Issue a device API key

```bash
KEY=$(curl -s -X POST "http://localhost:8000/api/v1/devices/$DEVICE_UUID/api-keys" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"name": "field-trial-fleet"}' | jq -r .api_key)

echo "$KEY"
# bbx_43c2af624721_5WAeDsj...
```

The plaintext is returned **once**; only its SHA-256 hash is stored. Flash it to
the device now — a lost key can be replaced, never recovered.

```bash
# List keys (metadata only, never the secret)
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_UUID/api-keys" -H "Authorization: Bearer $ACCESS" | jq

# Revoke immediately and permanently
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
  "http://localhost:8000/api/v1/devices/$DEVICE_UUID/api-keys/$KEY_ID" -H "Authorization: Bearer $ACCESS"
# 204
```

## 14. Device heartbeat

```bash
curl -s -X POST http://localhost:8000/api/v1/devices/heartbeat \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"firmware_version": "1.5.0"}' | jq
```

Authenticated by the key alone. A device may report its firmware version here,
so an OTA update is reflected without anyone editing the record. A device that
checks in while marked `inactive` is flipped back to `active`; a `maintenance`
or `decommissioned` status is left alone, because that was an operator's
decision.

## 15. Submit a crash report

This is the path firmware takes.

```bash
curl -s -X POST http://localhost:8000/api/v1/crashes \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{
        "firmware_version": "1.4.2",
        "build_version": "a1b2c3d",
        "timestamp": "2026-07-27T09:14:22Z",
        "fault_type": "HardFault",
        "task_name": "SensorTask",
        "pc": "0x08001A2C",
        "lr": "0x08001A0F",
        "sp": "0x20017FA0",
        "registers": {
          "r0": "0x00000000", "r1": "0x20000100", "r2": "0xDEADBEEF",
          "xpsr": "0x61000000", "cfsr": "0x00000400"
        },
        "stack": ["0x08001A2C", "0x20017FB0", "0x08001998"]
      }' | jq
```

```json
{
  "id": "3f1c...",
  "status": "new",
  "severity": "critical",
  "fault_type": "hard_fault",
  "received_at": "2026-07-27T09:14:25Z",
  "warnings": []
}
```

The key identifies the device, so `device_id` in the body is optional — and
ignored. A device cannot file a crash against someone else's hardware.

### The parser is deliberately forgiving

A different firmware build sending camelCase and integers works identically:

```bash
curl -s -X POST http://localhost:8000/api/v1/crashes \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"firmwareVersion":"2.0.0","faultType":"busFault",
       "taskName":"CommsTask","programCounter":134225964}' | jq .fault_type
# "bus_fault"
```

A badly malformed report is still stored, with the problems reported:

```bash
curl -s -X POST http://localhost:8000/api/v1/crashes \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"firmware_version":"1.5.0","fault_type":"???",
       "timestamp":"whenever","pc":"junk"}' | jq
```

```json
{
  "fault_type": "unknown",
  "severity": "medium",
  "warnings": [
    "timestamp: could not interpret 'whenever', using time of receipt",
    "fault_type: unrecognised value '???'",
    "program_counter: could not interpret 'junk' as an address"
  ]
}
```

Only two things are refused: a report with no fault evidence at all (**422**),
and a timestamp more than a day in the future (**422** — check the device
clock).

### Duplicate suppression

A device that retries an upload it never saw acknowledged gets the same report
back rather than creating a second row:

```json
{ "id": "3f1c...", "warnings": ["duplicate of a report received moments ago"] }
```

### Submitting on a device's behalf

An `engineer` may submit with a bearer token, in which case `device_id` (or the
serial number) is required:

```bash
curl -s -X POST http://localhost:8000/api/v1/crashes \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"device_id":"STM32-F4-0001","firmware_version":"1.4.2","fault_type":"HardFault"}' | jq
```

An unregistered device gives **404** — register it first.

## 16. Search crash history

```bash
curl -s "http://localhost:8000/api/v1/crashes?fault_type=hard_fault&severity=critical" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/crashes?device=STM32-F4-0001" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/crashes?firmware_version=1.4.2&status=new" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/crashes?task_name=SensorTask&sort=-occurred_at" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/crashes?q=dma" -H "Authorization: Bearer $ACCESS" | jq

FROM=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ)
curl -s "http://localhost:8000/api/v1/crashes?occurred_from=$FROM" -H "Authorization: Bearer $ACCESS" | jq
```

List rows omit the register and stack dumps — a page of 50 crashes would
otherwise ship megabytes of hex the table never renders. Fetch one report to
see them:

```bash
curl -s "http://localhost:8000/api/v1/crashes/$CRASH_ID" -H "Authorization: Bearer $ACCESS" | jq
```

```json
{
  "program_counter": 134224428,
  "register_dump": { "r0": 0, "r1": 536871168, "psr": 1627389952, "cfsr": 1024 },
  "stack_dump": { "start_address": null, "words": [134224428, 537001904] },
  "device": { "device_id": "STM32-F4-0001", "hardware_model": "STM32F407VG" }
}
```

Addresses come back as integers. Format them as hex client-side:
`(134224428).toString(16)` → `08001a2c`.

## 17. Triage a crash

```bash
curl -s -X PATCH "http://localhost:8000/api/v1/crashes/$CRASH_ID" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"status":"investigating","severity":"high","notes":"DMA races the ADC ISR"}' | jq
```

Only `status`, `severity` and `notes` can change. Registers, addresses and
dumps are immutable — they are the only account of what the device actually
did. Fields sent for anything else are ignored, not rejected.

Statuses: `new`, `triaged`, `investigating`, `resolved`, `ignored`, `duplicate`.

## 18. Device crash counters

```bash
curl -s "http://localhost:8000/api/v1/devices/$DEVICE_UUID/stats" -H "Authorization: Bearer $ACCESS" | jq
# {"total_crashes": 12, "open_crashes": 5, "crashes_last_24h": 2, "last_crash_at": "..."}
```

## 19. Deletion (admin only)

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
  "http://localhost:8000/api/v1/crashes/$CRASH_ID" -H "Authorization: Bearer $ADMIN_ACCESS"

# Deleting a device cascades to its entire crash history.
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
  "http://localhost:8000/api/v1/devices/$DEVICE_UUID" -H "Authorization: Bearer $ADMIN_ACCESS"
```

Engineers get **403** here by design. Prefer marking a crash `ignored` or a
device `decommissioned` — deleting removes evidence that analytics and future
diagnoses depend on.

---

# Phase 2.5 — Crash Analysis Engine

## 20. Upload a firmware build (ELF or MAP)

Symbolization needs the build's symbol table. Upload the ELF an engineer built,
indexed by the `firmware_version` (and optional `build_version`) that devices
report.

```bash
curl -s -X POST http://localhost:8000/api/v1/builds \
  -H "Authorization: Bearer $ACCESS" \
  -F "firmware_version=1.4.2" \
  -F "build_version=a1b2c3d" \
  -F "hardware_model=STM32F407VG" \
  -F "file=@firmware.elf" | jq
```

```json
{
  "id": "7c3e...",
  "status": "indexed",
  "artifact_type": "elf",
  "arch": "ARM",
  "has_debug_info": true,
  "symbol_count": 1284,
  "message": "Indexed 1,284 symbols with debug info."
}
```

Requires `engineer`. The type is detected from the file **contents**, not its
name — an ELF called `firmware.map` is still an ELF. A MAP file gives function
names only (no line numbers); an ELF with DWARF gives `file:line`. Re-uploading
for the same `(firmware_version, build_version)` **replaces** the artifact.

```bash
# List and inspect builds
curl -s "http://localhost:8000/api/v1/builds?firmware_version=1.4.2" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/builds/$BUILD_ID" -H "Authorization: Bearer $ACCESS" | jq

# Delete (admin only) - removes the artifact file and its symbols
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
  "http://localhost:8000/api/v1/builds/$BUILD_ID" -H "Authorization: Bearer $ADMIN_ACCESS"
```

## 21. A symbolized crash

Once the build is indexed, submit a crash exactly as in Phase 2. Fetch it and
the addresses are now resolved:

```bash
curl -s "http://localhost:8000/api/v1/crashes/$CRASH_ID" -H "Authorization: Bearer $ACCESS" | jq .symbolication
```

```json
{
  "symbolized": true,
  "build_version": "a1b2c3d",
  "pc": {
    "address_hex": "0x08001A2C",
    "function": "vTaskDelay",
    "offset": 28,
    "source_file": "tasks.c",
    "line": 1432,
    "resolved": true,
    "display": "vTaskDelay+0x1C at tasks.c:1432"
  },
  "frames": [
    { "origin": "pc", "display": "vTaskDelay+0x1C at tasks.c:1432" },
    { "origin": "lr", "display": "prvIdleTask+0x40 at tasks.c:3210" },
    { "origin": "stack", "display": "main+0x88 at main.c:74" }
  ],
  "resolved_count": 3,
  "warnings": []
}
```

The report also gains `top_function`, `crash_signature`, and a `group`.

If no build has been uploaded yet, the crash still stores fine — `symbolized`
is `false`, the frames carry raw addresses, and a warning explains that an ELF
should be uploaded.

## 22. Re-symbolize after a late upload

Crashes collected before the ELF existed are upgraded in place:

```bash
# Re-run for one crash
curl -s -X POST "http://localhost:8000/api/v1/crashes/$CRASH_ID/symbolicate" \
  -H "Authorization: Bearer $ACCESS" | jq .symbolized

# Re-run for every crash matching a build
curl -s -X POST "http://localhost:8000/api/v1/builds/$BUILD_ID/resymbolicate" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"limit": 500}' | jq
# {"processed": 213, "upgraded": 209, "total_matching": 213}
```

## 23. Crash groups — one row per bug

A fleet hitting one defect produces thousands of crash reports. Groups collapse
them:

```bash
curl -s "http://localhost:8000/api/v1/crash-groups?status=open&sort=-occurrence_count" \
  -H "Authorization: Bearer $ACCESS" | jq '.items[0]'
```

```json
{
  "signature": "2bf9ee03291a3038...",
  "title": "hard fault in vTaskDelay",
  "top_function": "vTaskDelay",
  "status": "open",
  "severity": "critical",
  "occurrence_count": 847,
  "device_count": 213,
  "first_seen_at": "2026-07-20T08:11:00Z",
  "last_seen_at": "2026-07-27T09:14:22Z",
  "affected_firmware_versions": ["1.4.2", "1.4.1"]
}
```

```bash
# The "most common root causes" list
curl -s "http://localhost:8000/api/v1/crash-groups/top?limit=10" -H "Authorization: Bearer $ACCESS" | jq

# Every occurrence of one bug
curl -s "http://localhost:8000/api/v1/crash-groups/$GROUP_ID/crashes" -H "Authorization: Bearer $ACCESS" | jq

# Filter crash history by group
curl -s "http://localhost:8000/api/v1/crashes?group_id=$GROUP_ID" -H "Authorization: Bearer $ACCESS" | jq
```

## 24. Triage the bug, not the occurrence

```bash
curl -s -X PATCH "http://localhost:8000/api/v1/crash-groups/$GROUP_ID" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"status": "resolved", "notes": "Fixed the DMA/ISR race in 1.5.0"}' | jq
```

Marking a group `resolved` is a claim about the **bug**. If a matching crash
arrives afterwards, the group flips to `regressed` automatically — a fix that
did not hold is more urgent than a fresh bug.

---

# Phase 3 — AI Diagnosis (RAG)

## 25. Build the knowledge base

The diagnosis engine answers **only** from the reference material you give it.
Upload STM32/FreeRTOS manuals, ARM Cortex-M references, engineering notes and
troubleshooting guides — as pasted text or as `.txt`/`.md` files.

```bash
# Ingest from pasted text (engineer)
curl -s -X POST "http://localhost:8000/api/v1/knowledge-base/documents" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{
    "title": "HardFault troubleshooting - FreeRTOS stack overflow",
    "source_type": "troubleshooting",
    "content": "A HardFault raised inside a FreeRTOS task is most often caused by a task stack overflow. When a task overflows its stack the memory access traps as a HardFault escalated from a bus fault. Check the CFSR and BFAR fault registers, enable configCHECK_FOR_STACK_OVERFLOW, and increase the task stack depth."
  }' | jq
```

```json
{
  "id": "6f1c...",
  "title": "HardFault troubleshooting - FreeRTOS stack overflow",
  "source_type": "troubleshooting",
  "status": "indexed",
  "chunk_count": 1,
  "embedding_model": "hashing-384",
  "indexed_at": "2026-07-30T10:00:00Z"
}
```

```bash
# Or upload a text file
curl -s -X POST "http://localhost:8000/api/v1/knowledge-base/documents/upload" \
  -H "Authorization: Bearer $ACCESS" \
  -F "file=@cortex-m4-fault-handling.md;type=text/markdown" \
  -F "source_type=arm_cortex_m" | jq '.status, .chunk_count'

# Corpus overview (viewer) - totals and the active providers
curl -s "http://localhost:8000/api/v1/knowledge-base/stats" \
  -H "Authorization: Bearer $ACCESS" | jq
```

Re-uploading identical content is a `409` — the corpus is deduplicated by
content hash, not silently doubled.

## 26. Semantic search over the corpus

```bash
curl -s -X POST "http://localhost:8000/api/v1/knowledge-base/search" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"query": "HardFault in a FreeRTOS task, stack overflow", "top_k": 5}' | jq
```

An `"empty": true` result is a real answer: the corpus has nothing relevant.
Only passages above the relevance floor come back — the first line of the
anti-hallucination defence.

## 27. Diagnose a crash (grounded)

```bash
curl -s -X POST "http://localhost:8000/api/v1/crashes/$CRASH_ID/diagnose" \
  -H "Authorization: Bearer $ACCESS" | jq
```

```json
{
  "id": "a2d0...",
  "crash_id": "…",
  "root_cause": "The hard_fault in `vTaskDelay` (task `SensorTask`) is consistent with the referenced material: A HardFault raised inside a FreeRTOS task is most often caused by a task stack overflow…",
  "recommended_fix": "Follow the remediation described in the cited reference and review the implementation of vTaskDelay against it.",
  "confidence_score": 0.34,
  "confidence_label": "likely",
  "is_uncertain": false,
  "top_relevance": 0.41,
  "sources": [
    {
      "document_title": "HardFault troubleshooting - FreeRTOS stack overflow",
      "source_type": "troubleshooting",
      "chunk_index": 0,
      "score": 0.41,
      "excerpt": "A HardFault raised inside a FreeRTOS task…"
    }
  ],
  "provider": "template",
  "model": "template-v1",
  "warnings": []
}
```

Every answer lists the **sources** it was built from, and the confidence is
grounded in retrieval quality — not the model's own claim.

## 28. Diagnose a crash (nothing relevant → explicitly uncertain)

With an empty or off-topic knowledge base, the same call refuses to guess:

```json
{
  "root_cause": "A hard_fault in vTaskDelay was reported, but no relevant reference material was found in the knowledge base to explain it. The cause cannot be determined with confidence from the available information.",
  "confidence_score": 0.1,
  "confidence_label": "uncertain",
  "is_uncertain": true,
  "sources": [],
  "warnings": [
    "retrieval found no sufficiently relevant reference material; diagnosis is not well grounded and is marked uncertain"
  ]
}
```

This is the anti-hallucination contract in action: **no context, no invented
answer.** Upload the relevant manual and re-run to get a grounded diagnosis.

## 29. Diagnosis history

```bash
# Every diagnosis for a crash, newest first (viewer)
curl -s "http://localhost:8000/api/v1/crashes/$CRASH_ID/diagnoses" \
  -H "Authorization: Bearer $ACCESS" | jq '.[] | {id, confidence_label, sources: (.sources|length)}'

# One diagnosis with full sources and provenance
curl -s "http://localhost:8000/api/v1/diagnoses/$DIAGNOSIS_ID" \
  -H "Authorization: Bearer $ACCESS" | jq
```

Re-running after adding a manual creates a **new** diagnosis to compare
against, never an overwrite — the history is the record of how understanding of
a bug improved.

## 30. Point the engine at a real model

No code changes — only configuration:

```bash
# OpenAI (or any OpenAI-compatible endpoint via OPENAI_BASE_URL)
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...

# A fully local stack via Ollama
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
```

The `/knowledge-base/stats` response reports which providers are live. Note
that switching the embedding provider means existing documents must be
re-indexed under the new model's vectors before they are retrievable again.
