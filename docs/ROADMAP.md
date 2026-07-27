# BlackBox Web Platform — Roadmap

Each phase ends with a working repository: source, tests, migrations, docs,
sample requests and a Docker Compose stack that starts.

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation, Authentication & RBAC | ✅ Complete |
| 2 | Devices & Crash Report API | ✅ Complete |
| 2.5 | Crash Analysis Engine (ELF/MAP, symbolization) | ⏳ Next |
| 3 | AI Diagnosis & RAG Knowledge Base | ⏸ Planned |
| 4 | Frontend Application | ⏸ Planned |
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

## Phase 2.5 — Crash Analysis Engine ⏳

**Deliverables**

- ELF/MAP file upload per firmware build, stored and indexed by build version.
- ELF parser (`pyelftools`) extracting the symbol table and section layout.
- `arm-none-eabi-addr2line` integration with a pure-Python fallback.
- Address → function → source file:line resolution for PC, LR and every stack
  frame.
- Stack-trace reconstruction from the raw stack dump: candidate return-address
  scanning, filtering against executable sections, frame ordering.
- Crash signature generation — a stable hash over the normalized top frames,
  fault type and task, so the same bug always produces the same signature.
- Duplicate detection: new crashes are linked to an existing crash group;
  the UI shows "seen 47 times across 12 devices" instead of 47 separate rows.
- Symbolization runs as a Celery task and degrades gracefully when no ELF has
  been uploaded for that build.

**Acceptance** — uploading the ELF for a build turns a raw PC value into
`vTaskDelay at tasks.c:1432`, and two identical crashes collapse into one group.

---

## Phase 3 — AI Diagnosis & RAG Knowledge Base

**Deliverables**

- `LLMProvider` abstraction: OpenAI first, Ollama/local behind the same
  interface, selected by `LLM_PROVIDER`.
- Document ingestion: STM32 reference manuals, FreeRTOS docs, ARM Cortex-M
  manuals, internal notes, previous crash reports, troubleshooting guides.
- Chunking, embedding and vector storage in ChromaDB with metadata filters.
- RAG pipeline: parsed crash + symbolization → retrieval → prompt → diagnosis.
- Structured output: root cause, recommended fix, confidence score, and the
  retrieved sources it relied on.
- **Anti-hallucination**: the model answers only from retrieved context; when
  retrieval is weak the diagnosis is returned as explicitly uncertain and
  labelled as such in the API, never dressed up as a confident answer.
- `ai_diagnoses` and `documents` tables, diagnosis history per crash.

**Acceptance** — a HardFault with a known cause yields a cited diagnosis; a
nonsense crash yields low confidence and an explicit "uncertain" verdict.

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
