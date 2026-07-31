# BlackBox Web Platform — Roadmap

Each phase ends with a working repository: source, tests, migrations, docs,
sample requests and a Docker Compose stack that starts.

| Phase | Title | Status |
|---|---|---|
| 1 | Foundation, Authentication & RBAC | ✅ Complete |
| 2 | Devices & Crash Report API | ✅ Complete |
| 2.5 | Crash Analysis Engine (ELF/MAP, symbolization) | ✅ Complete |
| 3 | AI Diagnosis & RAG Knowledge Base | ✅ Complete |
| 4 | Frontend Application | ✅ Complete |
| 5 | Dashboard, Analytics, Export & Notifications | ✅ Complete |
| 6 | Production Hardening & CI/CD | ✅ Complete |

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

## Phase 4 — Frontend Application ✅

**Delivered**

- React 19 + TypeScript (strict) + Vite 6 + Tailwind CSS v4 SPA, with TanStack
  Query for server state, React Router v7, and Axios.
- Axios client with a **transparent, single-flighted refresh-on-401**: an
  expired access token is rotated via the refresh token and the original
  request replayed; a failed refresh clears the session and routes to login.
- **Role-aware** routing and controls (`admin` > `engineer` > `viewer`), mirror
  of the backend's `require_roles`; route guards `RequireAuth`/`RequireRole`.
- Screens: login, register, forgot/reset password, profile (update + change
  password); device list and detail (stats, API keys, edit, delete, recent
  crashes); crash list and detail (**symbolized stack trace + AI diagnosis
  panel** with cited sources and history); crash groups list and detail with
  triage; knowledge base (stats, semantic search, add/upload documents,
  delete); user administration (admin).
- Dark/light theme over semantic CSS-variable tokens with a no-flash pre-paint
  script; responsive from phone to desktop; loading/empty/error states on every
  data view.
- TS types hand-mirrored from the Pydantic schemas so a contract change is a
  compile error. 20 Vitest tests (formatting, password policy, token store, API
  error unwrapping, login render). Type-check, ESLint and production build all
  clean.
- Multi-stage `Dockerfile` (Node build → nginx) that serves the static bundle
  and reverse-proxies `/api` to the backend; `frontend` service added to
  `docker-compose.yml`.

Details: [`architecture/phase-4.md`](architecture/phase-4.md).

---

## Phase 5 — Dashboard, Analytics, Export & Notifications ✅

**Delivered**

- Analytics layer (`AnalyticsRepository` + `AnalyticsService`) over the existing
  tables — no new analytics tables. Endpoints: dashboard `summary`,
  `crash-trend` (gap-filled daily counts + critical split), `fault-distribution`,
  `firmware-comparison`, `device-reliability` (per-device and fleet MTBF) and
  `confidence-distribution`. Derived figures (health score, MTBF, trend
  gap-fill) are defined once in the service; day-bucketing is dialect-aware so
  the SQLite tests exercise the PostgreSQL code path.
- **Export**: `/export/crashes.csv` (stdlib `csv`, filtered like the list view,
  bounded) and `/export/analytics.pdf` (a one-page ReportLab report, imported
  lazily so the dependency is only needed when a PDF is requested).
- **Notifications & alerts**: `notifications` + `alert_settings` tables
  (migration `0005`); per-user inbox (list, unread count, mark read/all).
  Critical-crash escalation is wired into ingestion as a best-effort collaborator
  — a crash at or above the configured severity raises one notification per
  eligible recipient (and an optional email), and never breaks ingestion if it
  fails. The threshold, recipients and email toggle are an admin-editable,
  database-stored policy that defaults from config.
- **Frontend**: a Dashboard (stat tiles, crash-trend chart, distributions, top
  root causes, CSV/PDF export), an Analytics page (7/30/90-day trend, firmware
  comparison, reliability table, confidence distribution), and a notification
  bell with a live unread badge, dropdown, inbox page and admin alert settings.
  Charts are hand-rolled against the data-viz method — one shared axis, status
  hues reserved and always labelled, theme-aware validated colours, hover
  tooltips.
- 19 new backend tests (404 total) and 6 new frontend tests (26 total); ruff,
  mypy, ESLint, tsc and both builds clean; migration `0005` parity verified;
  live smoke covers every Phase 5 endpoint (90 checks).

Details: [`architecture/phase-5.md`](architecture/phase-5.md).

---

## Phase 6 — Production Hardening & CI/CD ✅

**Delivered**

- **CI** (`.github/workflows/ci.yml`): four jobs on every push/PR — backend
  (ruff, mypy, `pytest --cov` with a coverage gate), frontend (tsc, eslint,
  vitest, build), security (`pip-audit --strict`, `npm audit`), and a docker
  image build. Coverage floor `fail_under = 78` in `pyproject.toml` (actual
  ~82%, with the Celery entrypoints excluded).
- **Production edge** (`docker-compose.prod.yml` + `nginx/nginx.conf`): a single
  TLS-terminating nginx front door; PostgreSQL, Redis, the backend and the SPA
  are internal-only. TLS 1.2/1.3, HSTS, a strict `Content-Security-Policy`
  (`script-src 'self'` — the SPA's theme bootstrap moved into the bundle to
  satisfy it), rate limiting (`/api` 20 r/s, `/api/v1/auth/` 5 r/min → 429), and
  the full security-header set as defence in depth.
- **ER diagram**: `backend/scripts/generate_er_diagram.py` derives a Mermaid ER
  diagram from `Base.metadata` (19 tables) so [`er-diagram.md`](architecture/er-diagram.md)
  never drifts from the schema.
- **Load profile**: a Locust file with device-ingest and engineer-browse user
  types, kept out of the unit suite.
- **Operations**: `scripts/backup.sh` / `scripts/restore.sh` (pg_dump/pg_restore,
  idempotent restore, optional artifact archive), a
  [backup/restore runbook](operations/backup-restore.md) and a
  [deployment guide](deployment.md) (TLS issuance, first start, upgrades,
  scaling). New `make` targets: `prod-up/down/logs`, `backup`, `restore`,
  `er-diagram`, `loadtest`, `coverage`.

Details: [`architecture/phase-6.md`](architecture/phase-6.md).

---

## The build is complete

All six phases (plus 2.5) are delivered: a production-ready, tested, documented
crash-diagnosis platform — API, AI, web app, analytics and the operational
tooling to run it.
