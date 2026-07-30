# BlackBox — AI-Powered Crash Diagnosis System for Embedded Firmware

Embedded devices (STM32 + FreeRTOS) crash in the field. The stack dump they
emit is a wall of hex that only a handful of engineers can read, and the
knowledge needed to read it is spread across reference manuals, old tickets and
people's heads.

**BlackBox is the web platform that receives those crash reports, symbolizes
them, diagnoses them with a retrieval-grounded LLM, and presents the result as
something an engineer can act on.**

> The firmware side is a separate module. This repository is the web platform:
> backend, AI service, frontend and deployment.

[![Phase](https://img.shields.io/badge/phase-2.5%20of%206-blue)]()
[![Tests](https://img.shields.io/badge/tests-346%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.12-blue)]()
[![License](https://img.shields.io/badge/license-MIT-lightgrey)]()

---

## Current status — Phase 2.5 complete

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation, authentication, RBAC, audit trail | ✅ Complete |
| 2 | Devices & crash report API, crash parser | ✅ Complete |
| **2.5** | Crash analysis engine (ELF/MAP, symbolization, signatures) | ✅ **Complete** |
| 3 | AI diagnosis & RAG knowledge base | ⏸ Planned |
| 4 | Frontend application | ⏸ Planned |
| 5 | Dashboard, analytics, export, notifications | ⏸ Planned |
| 6 | Production hardening & CI/CD | ⏸ Planned |

Full plan: [`docs/ROADMAP.md`](docs/ROADMAP.md).

### What works today

**Authentication & access control**
- Register, login, logout, refresh, forgot/reset password, change password
- JWT access tokens with **rotating** refresh tokens and server-side revocation
- Role-based access control: `admin`, `engineer`, `viewer`
- User administration: create, search, filter, paginate, assign roles, delete
- Account lockout after repeated failures; enumeration-resistant auth responses

**Device fleet**
- Register devices with serial, firmware, hardware model, owner, location, tags
- Search and filter by status, model, firmware, tag, owner, last-seen
- Per-device API keys so firmware can authenticate without an interactive login
- Heartbeat check-in that reports firmware version and revives inactive devices
- Per-device crash counters

**Crash reports**
- Ingestion endpoint for firmware, authenticated by device API key
- Parser that normalises field aliases, hex/decimal addresses, ISO/epoch
  timestamps, register and stack dumps across firmware dialects
- Automatic fault classification and severity derivation
- Duplicate suppression for retried uploads
- Crash history with filtering by device, firmware, fault type, severity,
  status, task and date range
- Triage workflow that leaves the forensic record immutable

**Crash analysis** *(Phase 2.5)*
- Upload firmware ELF/MAP artifacts; symbols indexed in-process (no cross
  toolchain needed in the container)
- Address → function → `file:line` symbolization via pyelftools + DWARF,
  with an optional external `addr2line` for inlined frames
- Stack-trace reconstruction from raw Cortex-M dumps (Thumb-bit + executable
  range filtering, no frame pointers required)
- Stable crash signatures over function names, so one bug groups across builds
- Crash groups: "seen 847 times across 213 devices", with worst-severity
  tracking and automatic regression detection
- Late-upload re-symbolization: crashes stored as raw hex are upgraded when
  their ELF arrives

**Platform**
- Append-only audit trail with an admin query API
- Liveness/readiness probes, structured JSON logs with request ids
- PostgreSQL schema with Alembic migrations, Redis + Celery worker and beat
- Swagger UI at `/docs`, ReDoc at `/redoc`

---

## Architecture

```
                        ┌──────────────────────┐
   STM32 + FreeRTOS ───▶│  Crash Ingest API    │  (Phase 2)
   device fleet         └──────────┬───────────┘
                                   │
   ┌───────────────┐    ┌──────────▼───────────┐    ┌──────────────────┐
   │  React SPA    │───▶│   FastAPI backend    │───▶│   PostgreSQL     │
   │  (Phase 4)    │◀───│  auth · RBAC · REST  │◀───│   users, devices │
   └───────────────┘    └──────────┬───────────┘    │   crashes, audit │
                                   │                └──────────────────┘
                        ┌──────────▼───────────┐    ┌──────────────────┐
                        │   Celery workers     │───▶│  Redis (broker)  │
                        │  parse · symbolize   │    └──────────────────┘
                        └──────────┬───────────┘
                                   │
                        ┌──────────▼───────────┐    ┌──────────────────┐
                        │   AI service         │───▶│  ChromaDB        │
                        │  RAG · LLM (Ph. 3)   │◀───│  vector store    │
                        └──────────────────────┘    └──────────────────┘
```

The backend follows clean architecture — **API → service → repository →
model** — so business rules stay testable and the LLM provider, email
transport and vector store are all swappable behind interfaces.

Details: [`docs/architecture/phase-1.md`](docs/architecture/phase-1.md) and
[`docs/architecture/phase-2.md`](docs/architecture/phase-2.md).

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic |
| Crash analysis | pyelftools (in-process ELF/DWARF), optional `addr2line` |
| Database | PostgreSQL 16 |
| Cache / queue | Redis 7, Celery |
| Auth | JWT (python-jose), bcrypt (passlib) |
| Logging | structlog (JSON in production) |
| AI *(Phase 3)* | LangChain, ChromaDB, OpenAI API — provider-swappable |
| Frontend *(Phase 4)* | React, TypeScript, Vite, Tailwind, React Query, Recharts |
| Deployment | Docker, Docker Compose, Nginx |
| Quality | pytest, pytest-asyncio, ruff, mypy |

---

## Quick start

### Option A — Docker (everything)

```bash
git clone <repository-url> blackbox && cd blackbox
cp .env.example .env
# Edit .env: set SECRET_KEY (openssl rand -hex 32) and FIRST_SUPERUSER_PASSWORD
docker compose up -d --build
```

The backend container waits for PostgreSQL, applies migrations, seeds the roles
and the bootstrap admin, then serves on **http://localhost:8000**.

```bash
curl -s http://localhost:8000/health | jq
open http://localhost:8000/docs
```

### Option B — Local backend, Docker infrastructure

```bash
cp .env.example .env
make setup      # create backend/.venv and install dependencies
make up         # start postgres + redis only
make migrate    # apply migrations
make seed       # create roles + bootstrap admin
make serve      # uvicorn with autoreload on :8000
```

### First login

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@blackbox.example.com","password":"ChangeMe123!"}' | jq
```

> Change `FIRST_SUPERUSER_PASSWORD` in `.env` before the first start of any
> deployment reachable by anyone else.

---

## Repository layout

```
blackbox/
├── backend/                 FastAPI application
│   ├── app/
│   │   ├── api/             HTTP layer
│   │   │   ├── deps.py      dependency wiring, auth, RBAC guards
│   │   │   └── v1/          versioned routes (auth, users, audit, health)
│   │   ├── core/            config, security, logging, errors, middleware
│   │   ├── db/              engine, session, declarative base, seeding
│   │   ├── models/          SQLAlchemy models
│   │   ├── repositories/    all SQL lives here
│   │   ├── schemas/         Pydantic request/response contracts
│   │   ├── services/        business rules (auth, users, email, audit)
│   │   ├── main.py          application factory
│   │   └── worker.py        Celery app and scheduled tasks
│   ├── alembic/             migrations
│   ├── tests/               unit + integration suites
│   └── Dockerfile
├── frontend/                React SPA                      (Phase 4)
├── ai-service/              RAG pipeline                   (Phase 3)
├── database/init/           PostgreSQL init scripts
├── docker/                  shared container assets
├── nginx/                   reverse proxy config           (Phase 6)
├── docs/
│   ├── ROADMAP.md
│   ├── architecture/phase-1.md
│   └── api/                 curl examples + .http collection
├── scripts/dev.sh           developer helper
├── docker-compose.yml
├── .env.example
└── Makefile
```

---

## API overview

Base path `/api/v1`. Interactive docs at `/docs`.

### Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | — | Create an account (gets `viewer`) |
| POST | `/auth/login` | — | Exchange credentials for a token pair |
| POST | `/auth/refresh` | — | Rotate the refresh token |
| POST | `/auth/logout` | Bearer | Revoke this session or all sessions |
| POST | `/auth/forgot-password` | — | Email a reset link |
| POST | `/auth/reset-password` | — | Consume the reset token |
| POST | `/auth/change-password` | Bearer | Change your own password |
| GET | `/auth/me` | Bearer | Current profile and roles |

### Users

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/users` | admin | List, search, filter, paginate |
| POST | `/users` | admin | Create with explicit roles |
| GET | `/users/roles` | admin | Assignable roles |
| GET | `/users/{id}` | admin | Fetch one |
| PATCH | `/users/{id}` | admin | Update, including roles and activation |
| DELETE | `/users/{id}` | admin | Delete |
| PATCH | `/users/me` | any | Update your own profile |

### Devices

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/devices` | viewer | List, search and filter the fleet |
| POST | `/devices` | engineer | Register a device |
| GET | `/devices/{id}` | viewer | Fetch one device |
| PATCH | `/devices/{id}` | engineer | Update (identifiers are immutable) |
| DELETE | `/devices/{id}` | admin | Delete, cascading to crash history |
| GET | `/devices/{id}/stats` | viewer | Crash counters |
| GET | `/devices/{id}/api-keys` | engineer | List key metadata |
| POST | `/devices/{id}/api-keys` | engineer | Issue a key (shown once) |
| DELETE | `/devices/{id}/api-keys/{key_id}` | engineer | Revoke a key |
| POST | `/devices/heartbeat` | device key | Device check-in |

### Crash reports

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/crashes` | device key or engineer | Submit a crash report |
| GET | `/crashes` | viewer | Search crash history |
| GET | `/crashes/{id}` | viewer | Full report with register/stack dumps |
| POST | `/crashes/{id}/symbolicate` | engineer | Re-run symbolization & grouping |
| PATCH | `/crashes/{id}` | engineer | Triage: status, severity, notes |
| DELETE | `/crashes/{id}` | admin | Delete a report |

### Firmware builds & crash groups *(Phase 2.5)*

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/builds` | viewer | List uploaded ELF/MAP artifacts |
| POST | `/builds` | engineer | Upload and index an ELF or MAP |
| GET | `/builds/{id}` | viewer | Build metadata and index status |
| POST | `/builds/{id}/resymbolicate` | engineer | Upgrade stored crashes for a build |
| DELETE | `/builds/{id}` | admin | Delete a build, its symbols and file |
| GET | `/crash-groups` | viewer | List distinct bugs |
| GET | `/crash-groups/top` | viewer | Most frequent open bugs |
| GET | `/crash-groups/{id}` | viewer | One group |
| GET | `/crash-groups/{id}/crashes` | viewer | Occurrences of one bug |
| PATCH | `/crash-groups/{id}` | engineer | Triage the underlying defect |

### Audit & health

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/audit-logs` | admin | Search the security audit trail |
| GET | `/health` | — | Liveness |
| GET | `/health/ready` | — | Readiness (PostgreSQL, Redis) |

Runnable examples: [`docs/api/curl-examples.md`](docs/api/curl-examples.md)
and [`docs/api/requests.http`](docs/api/requests.http).

### Error format

Every failure returns the same envelope:

```json
{
  "error": {
    "code": "permission_denied",
    "message": "This action requires one of the following roles: admin",
    "details": { "required_roles": ["admin"] }
  }
}
```

---

## Roles

| Role | Can do |
|---|---|
| `admin` | Everything, including user management, deletion and the audit trail |
| `engineer` | Register/edit devices, issue keys, submit/triage crashes, upload builds |
| `viewer` | Read-only access to devices, crash history and dashboards |

Admins implicitly satisfy every role check, so routes declare the minimum role
they need.

**Deletion is admin-only on purpose.** Deleting a device cascades to its entire
crash history. Engineers who want a unit out of the way set its status to
`decommissioned`, which also stops its API keys from working.

**Devices authenticate with API keys, not JWTs.** Firmware cannot perform an
interactive login, so each device gets a long-lived key
(`bbx_<prefix>_<secret>`) presented in `X-API-Key`. Only the SHA-256 hash is
stored; the plaintext is shown once at creation. The key identifies the device,
so a device cannot file a crash against someone else's hardware.

---

## Security

- **bcrypt** password hashing; policy of ≥10 characters with mixed classes.
- **Refresh-token rotation** — each refresh revokes the token presented, so a
  stolen token is usable at most once and replay is detectable.
- **Server-side revocation** — only the token `jti` is stored, and logout,
  password reset and deactivation flip `revoked_at`.
- **Account lockout** after `MAX_FAILED_LOGIN_ATTEMPTS` failures.
- **Enumeration resistance** — unknown email and wrong password are
  indistinguishable in both status and timing; `forgot-password` always returns
  the same message.
- **Reset tokens** are single use, time-limited, and stored only as a SHA-256
  hash.
- **No privilege escalation** — `roles` is ignored on `PATCH /users/me`; an
  admin cannot demote or delete themselves.
- **Security headers** on every response; HSTS in production.
- **Audit trail** of logins, failures, lockouts, role changes and resets.

---

## Testing

```bash
make test                                   # full suite
cd backend && .venv/bin/python -m pytest tests/unit -v
cd backend && .venv/bin/python -m pytest --cov=app --cov-report=html
```

346 tests run against an in-memory SQLite database with the real schema, so no
PostgreSQL server is needed:

| Suite | Tests | Covers |
|---|---|---|
| `tests/unit/test_crash_parser.py` | 102 | Aliases, address/timestamp formats, fault classification, register and stack dumps, realistic firmware payloads |
| `tests/unit/test_symbolizer.py` | 32 | Symbol/DWARF resolution, stack reconstruction, signatures — against a real compiled ELF |
| `tests/unit/test_elf_parser.py` | 21 | ELF/MAP parsing, Thumb handling, address index |
| `tests/unit/test_security.py` | 15 | bcrypt, JWT signing/expiry/tampering, opaque tokens |
| `tests/unit/test_schemas.py` | 15 | Password policy, pagination arithmetic |
| `tests/integration/test_devices_api.py` | 36 | Device CRUD, RBAC, tags, search, API keys, heartbeat |
| `tests/integration/test_crashes_api.py` | 37 | Ingestion auth, parsing, duplicates, history, triage, cascade |
| `tests/integration/test_symbolication.py` | 16 | End-to-end symbolization, grouping, degradation, regression |
| `tests/integration/test_builds_api.py` | 13 | Build upload, indexing, replace, RBAC, deletion |
| `tests/integration/test_auth_api.py` | 33 | Registration, login, lockout, rotation, reset, audit |
| `tests/integration/test_users_api.py` | 17 | RBAC, search, role changes, self-service guards |
| `tests/integration/test_health_api.py` | 9 | Probes, error envelope, middleware, OpenAPI |
| `tests/integration/test_init_db.py` | 8 | Idempotent seeding, bootstrap admin validation |

The suite enables `PRAGMA foreign_keys=ON` for SQLite so `ON DELETE CASCADE`
behaves as it does on PostgreSQL — without it the tests would pass while the
same delete orphaned rows in production.

### End-to-end smoke test

`make test` runs against an in-memory database. To verify a *running* stack —
middleware order, RBAC, token rotation, the audit trail — run the smoke test
against it:

```bash
make smoke                                   # http://localhost:8000
BASE_URL=https://staging.example.com ./scripts/smoke.sh
```

It performs 60+ HTTP checks and exits non-zero on the first mismatch. It creates
and deletes users, so point it at development or staging, never production.

Quality gates:

```bash
make lint    # ruff check + ruff format --check + mypy
```

---

## Configuration

All configuration is environment-driven; see [`.env.example`](.env.example) for
the annotated list. The most important values:

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev placeholder | **Must** be changed; `openssl rand -hex 32` |
| `ENVIRONMENT` | `local` | `production` disables `/docs` and enables HSTS |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access-token lifetime |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `20160` | 14 days |
| `MAX_FAILED_LOGIN_ATTEMPTS` | `5` | Lockout threshold |
| `EMAIL_BACKEND` | `console` | `smtp` for real delivery |
| `BACKEND_CORS_ORIGINS` | localhost:5173,3000 | Comma-separated |
| `FIRST_SUPERUSER_PASSWORD` | `ChangeMe123!` | **Change before first start** |

---

## Database migrations

```bash
cd backend
.venv/bin/alembic upgrade head                        # apply
.venv/bin/alembic revision --autogenerate -m "add devices"
.venv/bin/alembic downgrade -1                        # roll back one
.venv/bin/alembic history --verbose
```

Migrations read the DSN from application settings, so the app and Alembic can
never disagree about which database they target.

---

## Make targets

```
make setup    Create the backend venv and install dependencies
make up       Start postgres + redis
make down     Stop all docker services
make migrate  Apply database migrations
make seed     Create default roles and the bootstrap admin
make serve    Run the API with autoreload
make worker   Run the Celery worker
make test     Run the backend test suite
make smoke    Run the end-to-end smoke test against a running API
make lint     Run ruff and mypy
make fmt      Auto-format the backend
make build    Build all docker images
make logs     Tail the backend logs
make clean    Remove containers, volumes and caches
```

---

## License

MIT
