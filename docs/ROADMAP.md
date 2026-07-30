# BlackBox Web Platform — Roadmap

Each phase ends with a working repository: source, tests, migrations, docs,
sample requests and a Docker Compose stack that starts.

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation, Authentication & RBAC | ✅ Complete |
| 2 | Devices & Crash Report API | ✅ Complete |
| 2.5 | Crash Analysis Engine (ELF/MAP, symbolization) | ✅ Complete |
| 3 | AI Diagnosis & RAG Knowledge Base | ✅ Complete |
| 4 | Frontend Application | ⏳ Next |
| 5 | Dashboard, Analytics, Export & Notifications | ⏸ Planned |
| 6 | Production Hardening & CI/CD | ⏸ Planned |

---

## Phase 1 — Foundation, Authentication & RBAC ✅

Monorepo skeleton, FastAPI core, PostgreSQL + SQLAlchemy 2.0 async + Alembic,
JWT auth with refresh rotation, RBAC, password reset, audit log, health checks,
Docker Compose, 76 tests.

Details: [`architecture/phase-1.md`](architecture/phase-1.md).

---

## Phase 2 — Devices & Crash Report API ✅

**Delivered**

- `devices`, `tags`, `device_tags`, `device_api_keys` and `crash_reports`
  tables with migration `0002`.
- Device CRUD with search and filtering by status, model, firmware, tag, owner
  and last-seen; `engineer` writes, `viewer` reads, `admin` deletes.
- Per-device API keys (`bbx_<prefix>_<secret>`), hashed at rest, revocable,
  optionally expiring — firmware cannot perform an interactive login.
- `POST /api/v1/crashes` accepting either a device key or an engineer JWT.
- Crash parser normalising field aliases, hex/decimal addresses, ISO-8601 and
  epoch timestamps, register dumps and stack dumps; classifies fault type and
  derives severity. Problems become warnings, not rejections.
- Duplicate suppression for retried uploads.
- Crash history with filters for device, firmware, build, fault type, severity,
  status, task and date range, plus sorting and pagination.
- Triage workflow (`status`, `severity`, `notes`) that leaves fault evidence
  immutable.
- Heartbeat endpoint and a Celery job that marks silent devices inactive.
- `reparse_crash_report` task — reprocesses a stored `raw_payload`, the hook
  Phase 2.5 extends.
- 188 new tests (264 total).

Details: [`architecture/phase-2.md`](architecture/phase-2.md).

---

## Phase 2.5 — Crash Analysis Engine ✅

**Delivered**

- `firmware_builds`, `build_symbols` and `crash_groups` tables (migration
  `0003`); crash reports gained symbolication, signature and grouping columns.
- ELF/MAP upload and in-process indexing via `pyelftools` — no cross toolchain
  in the container. Type detected from content, not filename; re-upload
  replaces.
- Symbolization: address → function+offset → `file:line` from DWARF, with an
  optional external `addr2line` for inlined frames. Degrades to names-only
  (stripped build / MAP) and to raw hex (no build), never failing.
- ARM Thumb-bit handling, made architecture-aware after the x86 test fixture
  exposed that unconditional normalization corrupts non-ARM addresses.
- Stack-trace reconstruction by scanning: Thumb-bit + executable-range
  filtering, innermost-first ordering, adjacent-duplicate collapse.
- Stable crash signatures over function names (clone suffixes stripped), with a
  build-scoped `pc + firmware_version` fallback when unsymbolized.
- Crash groups with transactional counters, worst-severity tracking and
  automatic regression detection; `/crash-groups`, `/crash-groups/top`,
  per-group crash listing and triage.
- Inline symbolization on ingest, plus `symbolicate_crash_report` and
  `resymbolicate_firmware` Celery tasks and a resymbolicate endpoint for late
  uploads.
- 82 new tests (346 total): 53 unit against a real compiled ELF, 29 integration.

Details: [`architecture/phase-2.5.md`](architecture/phase-2.5.md).

---

## Phase 3 — AI Diagnosis & RAG Knowledge Base ✅

**Delivered**

- `documents`, `document_chunks` and `ai_diagnoses` tables (migration `0004`);
  diagnosis history kept per crash and per group.
- Three provider seams, each an interface with a deterministic offline default
  and HTTP-backed real options, selected purely by configuration:
  `LLMProvider` (`LLM_PROVIDER` = template | openai | ollama),
  `EmbeddingProvider` (`EMBEDDING_PROVIDER` = hashing | openai | ollama),
  `VectorStore` (`VECTOR_STORE` = database | chroma). OpenAI/Ollama are called
  over REST via `httpx` — no vendor SDK is a hard dependency.
- Document ingestion for STM32 references, FreeRTOS docs, ARM Cortex-M manuals,
  engineering notes, previous crash reports and troubleshooting guides — as
  pasted text or `.txt`/`.md` upload; chunked with overlap, embedded, and
  deduplicated by content hash.
- Semantic search over the corpus with a relevance floor, so an off-topic query
  returns nothing rather than noise.
- RAG diagnosis pipeline: symbolized crash → query → retrieval → grounded prompt
  → structured diagnosis (root cause, recommended fix, summary, confidence,
  cited sources).
- **Anti-hallucination enforced in code, not just the prompt**: confidence is
  derived from retrieval quality and capped by the best match, the model's own
  claim can only lower it, and a crash with no sufficiently relevant references
  comes back explicitly `uncertain` with zero sources.
- Built without LangChain — every step is a plain, unit-tested function — and
  fully testable offline: the default template LLM + hashing embeddings +
  database vector store need no API key and no extra services.
- 39 new tests (385 total): 19 unit (chunking, embeddings, cosine, template
  grounding), 20 integration (ingestion, dedup, RBAC, search, grounded and
  ungrounded diagnosis, anti-hallucination, history).

**Acceptance met** — a HardFault whose cause is in the knowledge base yields a
cited, non-uncertain diagnosis; the same crash against an empty or off-topic
corpus yields an explicit `uncertain` verdict with no invented sources. Verified
by the test suite and a live end-to-end smoke run (73 checks).

Details: [`architecture/phase-3.md`](architecture/phase-3.md).

---

## Phase 4 — Frontend Application

React 19 + TypeScript + Vite + Tailwind, React Query, React Router, Axios with
token-refresh interceptors, protected routes by role, dark/light theme,
responsive layout. Screens: login, register, forgot/reset password, device
list and detail, crash list and detail with symbolized stack trace, user
administration.

---

## Phase 5 — Dashboard, Analytics, Export & Notifications

Dashboard tiles (total/online devices, crashes today, fault-type counts, AI
diagnoses, device health score, most common root causes). Charts: crash trend,
crash frequency, fault distribution, firmware comparison, device reliability,
AI confidence distribution, MTBF. CSV and PDF export. Email alerts, web
notifications, configurable alert thresholds, critical-crash escalation.

---

## Phase 6 — Production Hardening & CI/CD

Nginx reverse proxy with TLS and rate limiting, production Compose file,
GitHub Actions (lint, type-check, test, build, scan), coverage gates,
ER diagram generation, load tests, backup/restore runbook, deployment guide.
