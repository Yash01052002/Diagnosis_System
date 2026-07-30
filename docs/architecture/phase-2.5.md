# Phase 2.5 — Crash Analysis Engine

## Objectives

1. Turn a raw crash address (`0x08001A2C`) into something an engineer can act
   on (`vTaskDelay+0x1c at tasks.c:1432`).
2. Do it without requiring a cross toolchain in the container.
3. Reconstruct a call chain from a raw Cortex-M stack dump, which has no frame
   pointers to walk.
4. Give every crash a stable **signature** so a thousand reports of one bug
   collapse into one group.
5. Degrade gracefully at every step — a crash report is evidence, and nothing
   here may discard it.

## The pipeline

```
 Crash report (stored)                  Firmware build (uploaded ELF/MAP)
   pc, lr, stack_dump.words                   symbols + section table + DWARF
        │                                             │
        └──────────────┬──────────────────────────────┘
                       ▼
        ┌──────────────────────────────────────────────┐
        │ 1. find_for_crash                            │
        │    match on (firmware_version, build_version)│
        │    ELF preferred over MAP; else no build     │
        └──────────────────────────────────────────────┘
                       ▼
        ┌──────────────────────────────────────────────┐
        │ 2. reconstruct_stack        stack_analyzer   │
        │    scan words → filter by Thumb bit +        │
        │    executable range → PC, LR, then frames    │
        └──────────────────────────────────────────────┘
                       ▼
        ┌──────────────────────────────────────────────┐
        │ 3. resolve each frame       symbolizer       │
        │    address → symbol (binary search)          │
        │    → DWARF file:line (pyelftools, in-proc)   │
        └──────────────────────────────────────────────┘
                       ▼
        ┌──────────────────────────────────────────────┐
        │ 4. build_signature          stack_analyzer   │
        │    hash of fault + task + top frame NAMES     │
        └──────────────────────────────────────────────┘
                       ▼
        ┌──────────────────────────────────────────────┐
        │ 5. assign_group             symbolication    │
        │    find-or-create group, bump counters       │
        └──────────────────────────────────────────────┘
```

Symbolication runs **inline on ingest** (it is a symbol-table lookup against an
already-loaded build, not a heavy job) and is also exposed as a Celery task and
two endpoints for re-processing.

## Symbolization without a cross toolchain

`pyelftools` reads the symbol table and DWARF line program **in-process**, so
the container needs no `arm-none-eabi-*` binaries. That matters because the
platform is deployed as an image and the firmware was built somewhere else
entirely.

Three resolution layers, each falling back to the next:

| Layer | Input | Output |
|---|---|---|
| DWARF via pyelftools | ELF with `-g` | `vTaskDelay+0x1c at tasks.c:1432` |
| Symbol table only | stripped ELF, or a MAP file | `vTaskDelay+0x1c` |
| None | no matching build | `0x08001A2C` (raw, flagged unresolved) |

An external `addr2line` can be configured (`ADDR2LINE_BINARY`) purely as an
*enhancement* — it resolves inlined frames, which the in-process path does not.
Its absence never breaks anything.

## The Thumb bit — and the bug the x86 test caught

On ARM Cortex-M, which is Thumb-only:

- a function **symbol**'s `st_value` has bit 0 **set** (`0x08001A2D`);
- the actual instruction address, and the DWARF line program, use the **even**
  address (`0x08001A2C`);
- a return address in `LR` is **odd** (bit 0 set).

So symbol lookup must clear bit 0 to match DWARF, and the stack scanner uses
the bit as a filter: a word with bit 0 set that also points into executable
memory is a plausible return address; a saved register or a loop counter is
not.

The test fixture is compiled on the host — **x86-64, not ARM**. On x86 a
function address may legitimately be odd (functions are byte-aligned), and it
is the *same* odd address in both the symbol table and DWARF. Clearing bit 0
there corrupted the symbol so it no longer matched DWARF, and line lookup
silently returned nothing.

The fix: **Thumb normalization is ARM-specific.** `is_arm_arch()` gates it in
the parser, and the `Symbolizer` carries a matching `normalize_thumb` flag so
runtime addresses are treated the same way the symbols were stored. Production
(ARM) clears the bit; the x86 test fixture does not. The value of testing
against a real compiled binary rather than a mock is exactly that it surfaced
this.

## Stack reconstruction — scanning, not walking

Embedded builds use `-fomit-frame-pointer`, so there is no frame chain to
walk. The dumped stack window is a mix of return addresses, saved registers,
locals and padding. Recovery is therefore a **scan**: every word is a
candidate return address, and false positives are filtered with two cheap,
hardware-grounded tests (`looks_like_return_address`):

1. **Thumb bit set** — a `BL`/`BLX` pushes `LR` with bit 0 set.
2. **Points into an executable section** — from the ELF's section table.

Frames are ordered innermost-first (PC, then LR, then stack finds). Adjacent
duplicates collapse (the PC, LR and a stack slot often land in one function);
non-adjacent repeats survive, because those are real recursion.

## Signatures — grouping the same bug

A signature is a hash over the **fault type, task, and the top few frame
_names_** — not addresses. Addresses move with every build; names do not. That
is what lets the same bug group together across firmware versions, which is the
whole point.

```
signature = sha256("v1|hard_fault|IDLE|vTaskDelay>prvIdleTask")[:32]
```

Two robustness details:

- **Clone suffixes stripped.** GCC emits `foo.constprop.0`, `foo.isra.3` for
  specialised copies; the same bug can produce different suffixes between
  builds, so they are removed before hashing.
- **Unsymbolized fallback is build-scoped.** With no symbols there are no names
  to hash, so the signature falls back to `pc + firmware_version`. That is
  deliberately build-scoped — the same bug in a later build lands at a
  different address and forms a new group — and `symbolized: false` is stored
  in the components to record why. Folding in the firmware version prevents
  accidental cross-build collisions.

## Crash groups

A `CrashGroup` is one row per distinct bug. Denormalised counters
(`occurrence_count`, `device_count`) are maintained transactionally on ingest —
recomputing them from `crash_reports` on every dashboard load would mean a
`COUNT DISTINCT` over the largest table in the system. Device count can't be a
simple increment (the same device crashing twice must not count twice), so it
is recomputed with a `COUNT(DISTINCT device_id)` scoped to the group.

Two behaviours worth calling out:

- **Worst severity wins.** A group carries the highest severity any occurrence
  ever reached, so a bug that is usually benign but sometimes critical is
  ranked by its worst case.
- **Automatic regression detection.** A group marked `resolved` that receives a
  new matching crash flips to `regressed` with a timestamp. A fix that did not
  hold is more urgent than a bug nobody has looked at yet.

## Data model additions

```
┌────────────────────┐         ┌──────────────────────┐
│  firmware_builds   │────1:N─<│    build_symbols     │
├────────────────────┤         ├──────────────────────┤
│ firmware_version   │         │ build_id      FK     │
│ build_version      │         │ name          IDX    │
│ artifact_type      │         │ address  BIGINT IDX  │  ← (build_id, address)
│ storage_path       │         │ size, kind           │     range lookup
│ sha256, build_id   │         └──────────────────────┘
│ status, arch       │
│ has_debug_info     │         ┌──────────────────────┐
│ symbol_count       │         │    crash_groups      │
│ sections   JSONB   │         ├──────────────────────┤
└────────────────────┘         │ signature      UQ    │
         ▲                      │ title, fault_type    │
         │ build_id (SET NULL)  │ top_function   IDX   │
         │                      │ status, severity     │
┌────────┴───────────┐          │ occurrence_count     │
│   crash_reports    │──group_id│ device_count         │
│   (+ Phase 2.5)    │─(SET NULL│ first/last_seen_at   │
├────────────────────┤   )─────>│ affected_fw JSONB    │
│ crash_signature IDX│          │ regressed_at         │
│ group_id        FK │          └──────────────────────┘
│ build_id        FK │
│ symbolication JSONB│
│ symbolicated_at    │
│ top_function    IDX│
└────────────────────┘
```

Design notes:

- **Symbols live in the database, not just the file.** Resolving a name is then
  an indexed range query, and it keeps working even if the artifact file is
  later pruned from disk — only source lines are lost then, which the API
  reports as a warning. `build_symbols` has no `updated_at`: symbols are
  written once at index time and a firmware image can carry tens of thousands
  of them, so they go in via a Core bulk insert.
- **`crash_reports.build_id` is `ON DELETE SET NULL`.** Deleting a build
  removes the ability to symbolize *new* crashes, not the symbolication already
  recorded on existing reports.
- **Re-upload replaces.** A rebuilt image for the same
  `(firmware_version, build_version, artifact_type)` supersedes its
  predecessor; keeping both would make symbolization ambiguous.

## What Phase 3 builds on

- `symbolication.frames` and `top_function` are the structured context a RAG
  prompt retrieves against — "a HardFault in `vTaskDelay` at `tasks.c:1432`" is
  a far better query than a hex address.
- `crash_signature` and `CrashGroup` mean a diagnosis is computed **once per
  bug**, not once per occurrence — the difference between one LLM call and a
  thousand.
- `signature_components` records what the grouping was based on, which a
  diagnosis can cite.
