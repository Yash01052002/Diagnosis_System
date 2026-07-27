# Phase 2 — Devices & Crash Report API

## Objectives

1. A device registry: identity, firmware, ownership, status, location, tags.
2. Credentials devices can actually use — firmware cannot perform an
   interactive login, so it authenticates with a per-device API key.
3. A crash ingestion endpoint that survives contact with real firmware.
4. A parser that normalises whatever a device sends into one canonical shape.
5. Crash history with the filters an engineer and a dashboard need.
6. Triage workflow that never mutates the forensic record.

## Ingestion pipeline

```
 Device (STM32 + FreeRTOS)
   │  POST /api/v1/crashes
   │  X-API-Key: bbx_<prefix>_<secret>
   ▼
┌──────────────────────────────────────────────────────────┐
│ 1. Authenticate                                          │
│    prefix → indexed lookup → SHA-256 compare on secret   │
│    The key identifies the device; the body cannot        │
└──────────────────────────────────────────────────────────┘
   ▼
┌──────────────────────────────────────────────────────────┐
│ 2. Parse and normalise      app/services/crash_parser.py │
│    aliases → addresses → timestamp → fault → severity    │
│    Problems become warnings, not rejections              │
└──────────────────────────────────────────────────────────┘
   ▼
┌──────────────────────────────────────────────────────────┐
│ 3. Resolve device + mark online                          │
│    A device that is crashing is not offline              │
└──────────────────────────────────────────────────────────┘
   ▼
┌──────────────────────────────────────────────────────────┐
│ 4. Duplicate check                                       │
│    same device + fault + PC within 60s → return existing │
└──────────────────────────────────────────────────────────┘
   ▼
┌──────────────────────────────────────────────────────────┐
│ 5. Persist + audit                                       │
│    normalised fields AND the original raw payload        │
└──────────────────────────────────────────────────────────┘
   ▼
   201 { id, fault_type, severity, warnings[] }
```

## The parser is the heart of this phase

Firmware in the field cannot be redeployed as easily as this service. A build
that ships with `firmwareVersion` instead of `firmware_version` will keep
sending that spelling for years. So the parser is **liberal in what it accepts
and strict in what it stores**:

| Input | Normalised to |
|---|---|
| `pc`, `PC`, `programCounter`, `program_counter` | `program_counter` |
| `"0x08001A2C"`, `"08001A2C"`, `"0x0800_1A2C"`, `134224428` | `134224428` |
| `"2026-07-27T09:14:22Z"`, `1769509422`, `1769509422000` | UTC datetime |
| `"HardFault"`, `"hard_fault"`, `"Hard Fault"`, `"HARDFAULT"` | `hard_fault` |
| `"IWDG timeout"`, `"watchdog reset"`, `"WDT"` | `watchdog_reset` |
| `{"R0":..., "XPSR":...}` or `[v0, v1, v2]` | `{"r0":…, "psr":…}` |
| `"0x1 0x2"`, `["0x1","0x2"]`, `{"words":[…]}` | `{"start_address":…, "words":[…]}` |

Three decisions worth calling out:

**Warnings, not rejections.** A report with an unreadable timestamp and a
garbage PC is still stored, with the problems listed in `warnings`. Crashes are
evidence; the ones hardest to parse are often the ones most worth keeping. Only
a report with no fault evidence at all, or a clock skewed by more than a day,
is refused.

**The raw payload is always kept.** `raw_payload` holds exactly what the device
sent. That is what makes `reparse_crash_report` possible: when the parser
learns a new firmware dialect, existing reports are upgraded in place rather
than staying frozen at whatever quality shipped first. It is also where Phase
2.5 attaches symbolization.

**One alias table, two consumers.** `CrashReportSubmit` builds its
`validation_alias` choices from the parser's own `FIELD_ALIASES`. A schema that
rejected `firmwareVersion` before the parser saw it would make the parser's
tolerance unreachable — and two hand-maintained lists would drift the first
time a new dialect appeared.

## Data model additions

```
┌──────────────┐        ┌───────────────┐        ┌──────────┐
│    users     │───┐    │    devices    │───┬───<│device_tags│>──┐
└──────────────┘   │    ├───────────────┤   │    └──────────┘   │
                   │    │ id         PK │   │                   ▼
        owner_id   └───>│ device_id  UQ │   │            ┌──────────┐
     (SET NULL)         │ serial_no  UQ │   │            │   tags   │
                        │ firmware_ver  │   │            │ name  UQ │
                        │ hardware_model│   │            └──────────┘
                        │ status        │   │
                        │ location      │   │
                        │ last_online_at│   │
                        └───────┬───────┘   │
                                │           │
              ┌─────────────────┘           └──────────────┐
              │ 1:N (CASCADE)                       1:N    │
              ▼                                            ▼
   ┌────────────────────┐                    ┌──────────────────────────┐
   │  device_api_keys   │                    │      crash_reports       │
   ├────────────────────┤                    ├──────────────────────────┤
   │ prefix          UQ │  ← indexed lookup  │ occurred_at / received_at│
   │ key_hash        UQ │  ← SHA-256         │ fault_type, exception    │
   │ name               │                    │ task_name                │
   │ expires_at         │                    │ program_counter  BIGINT  │
   │ last_used_at       │                    │ link_register    BIGINT  │
   │ revoked_at         │                    │ stack_pointer    BIGINT  │
   └────────────────────┘                    │ register_dump    JSONB   │
                                             │ stack_dump       JSONB   │
                                             │ raw_payload      JSONB   │
                                             │ parse_warnings   JSONB   │
                                             │ severity, status, notes  │
                                             │ ai_diagnosis     (Ph. 3) │
                                             │ confidence_score (Ph. 3) │
                                             └──────────────────────────┘
```

Design notes:

- **`BIGINT` for addresses.** A signed 32-bit column cannot hold an address
  above `0x7FFFFFFF`, which is most of the address space on a Cortex-M part.
- **Tags are a table, not a JSON array.** Two devices labelled `field-trial`
  point at one row, so listing and filtering tags is an indexed join rather
  than a JSON scan.
- **API keys store only the hash.** The `prefix` is public and indexed so a
  presented key can be located in one lookup; without it, verification would
  have to hash the candidate against every stored key.
- **Composite indexes** on `(device_id, occurred_at)` and
  `(fault_type, occurred_at)` — the two hottest queries the dashboard runs.

## Authorization

| Action | Role |
|---|---|
| Read devices and crashes | `viewer` |
| Register / edit devices, issue and revoke API keys | `engineer` |
| Submit crash reports | device API key, or `engineer` |
| Triage crashes (status, severity, notes) | `engineer` |
| Delete a device or a crash report | `admin` |

Deletion is admin-only on purpose. Deleting a device cascades to its entire
crash history; engineers who want a unit out of the way set its status to
`decommissioned`, which also stops its API keys from working.

**Fault evidence is immutable.** `PATCH /crashes/{id}` accepts only status,
severity and notes. Registers, addresses and dumps cannot be edited by anyone —
they are the only account of what the device actually did.

## Two bugs the tests caught

Worth recording, because both would have shipped silently:

1. **The strict schema defeated the permissive parser.** `CrashReportSubmit`
   required `firmware_version`, so a camelCase firmware got a 422 before
   normalisation ever ran. Fixed by sourcing the schema's aliases from the
   parser's table.

2. **Cascade deletes silently did nothing under test.** SQLite ignores
   `ON DELETE CASCADE` unless `PRAGMA foreign_keys=ON` is set per connection,
   and the relationship was `lazy="noload"` so the ORM did not cascade either.
   Deleting a device left orphaned crash rows — on SQLite only. The suite was
   passing while the equivalent PostgreSQL behaviour differed. Fixed by
   enabling the pragma for every SQLite connection and adding
   `passive_deletes=True`, which also avoids loading a device's entire crash
   history into memory just to delete it.

## What Phase 2.5 builds on

- `raw_payload` + `reparse_crash_report` are the re-processing hook.
- `program_counter`, `link_register` and `stack_dump.words` are the addresses
  to symbolize.
- `find_recent_duplicate` is the exact-match placeholder that signature-based
  grouping replaces.
- `build_version` is the key an uploaded ELF/MAP will be indexed by.
