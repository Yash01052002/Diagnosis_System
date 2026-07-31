# Phase 6 — Production Hardening & CI/CD

The final phase adds no product features. It makes the platform **shippable and
keepable**: a CI pipeline that gates every change, a hardened production edge, a
schema diagram that can't drift, a load profile, and a backup/restore runbook.

## Continuous integration

`.github/workflows/ci.yml` runs four jobs on every push and PR:

| Job | What it enforces |
|---|---|
| **backend** | `ruff check`, `mypy`, and `pytest --cov` with a coverage floor |
| **frontend** | `tsc -b`, `eslint`, `vitest`, and a production `vite build` |
| **security** | `pip-audit --strict` on backend deps, `npm audit --audit-level=high` on frontend deps |
| **docker** | builds both images (backend + frontend) with cached layers |

The gates are the same ones used throughout development, now made mandatory:
nothing merges that fails lint, types, tests, the build, or a known-vulnerable
dependency check.

### Coverage gate

`pyproject.toml` sets `[tool.coverage.report] fail_under = 78`, so
`pytest --cov=app` fails the build if line coverage regresses. `app/worker.py`
(the Celery entrypoints, exercised out-of-process in production) is excluded so
the number reflects what the suite actually asserts — currently **~82%**.

## The production edge

Development runs each service on its own host port. Production puts a single
**nginx edge** in front of everything and closes the rest off
(`docker-compose.prod.yml`): PostgreSQL, Redis, the backend and the SPA are
reachable only on the internal network, and only the edge publishes 80/443.

```
                    ┌────────────────────────────────────────┐
   :80  ──redirect──▶ 443  edge (nginx)                        │
   :443 ─TLS term───▶  · rate limit  /api 20r/s · /auth 5r/min │
                     │  · security headers (HSTS, CSP, …)      │
                     │  /api,/health → backend:8000            │
                     │  /            → frontend:80 (SPA)        │
                     └────────────────────────────────────────┘
        (postgres · redis · backend · frontend · worker · beat — internal only)
```

What the edge enforces, beyond routing:

- **TLS** 1.2/1.3 with a modern cipher list, session tickets off, HSTS.
- **Rate limiting** keyed on the real client IP: a general `/api` bucket and a
  deliberately tight `/api/v1/auth/` bucket (a login form's cadence, not a
  credential-stuffing script's), returning `429` past the burst.
- **Security headers** as defence in depth — the app's middleware already sets
  them, and the edge sets them again so a misconfigured upstream can't drop
  them. The **CSP is strict**: `script-src 'self'`, no inline scripts. That is
  why the SPA's theme-bootstrap moved out of an inline `<script>` and into the
  bundle in this phase — the app now satisfies a no-`unsafe-inline` script
  policy.
- **Request-time upstream resolution** via Docker DNS, so the edge starts even
  before the backend is up and picks it up when it appears.

The backend image was already hardened in earlier phases (multi-stage build,
non-root user, healthcheck, an entrypoint that waits for the database, migrates
and seeds) — Phase 6 wraps it in the edge and the internal network.

## Schema diagram that can't drift

`backend/scripts/generate_er_diagram.py` walks `Base.metadata` and emits a
**Mermaid** ER diagram — every table, its columns (with `PK`/`FK` markers) and
the relationships implied by the foreign keys. Because it is generated from the
models, [`er-diagram.md`](er-diagram.md) is always the real schema; regenerate
it after a model change with `make er-diagram`. The current schema is **19
tables**.

## Load profile

`backend/tests/load/locustfile.py` describes two weighted user types that mirror
real traffic — firmware devices POSTing crashes (the write-heavy ingest path)
and engineers browsing crashes and the dashboard (the read path the analytics
queries back). It runs against a seeded non-production stack:

```bash
pip install locust
BASE_URL=… DEVICE_API_KEY=… ENGINEER_EMAIL=… ENGINEER_PASSWORD=… \
  locust -f backend/tests/load/locustfile.py --host "$BASE_URL"
```

It is intentionally *not* part of the unit suite (the filename doesn't match the
test glob, so pytest never imports it) — load testing is a deliberate,
resourced activity, not a per-commit gate.

## Backups & operations

`scripts/backup.sh` / `scripts/restore.sh` wrap `pg_dump` / `pg_restore` against
the `db` container (custom format, idempotent restore, artifact-volume archive
optional). The knowledge-base vectors live in the database, so one dump captures
the RAG corpus too. The [backup/restore runbook](../operations/backup-restore.md)
covers scheduling, off-host retention, backup verification, and a disaster-recovery
outline; the [deployment guide](../deployment.md) covers TLS issuance, first
start, upgrades and scaling.

## What "done" means here

- CI is green on all four jobs; the coverage floor holds at 78% (actual ~82%).
- The production stack `docker compose config` validates; the edge config is a
  complete TLS + rate-limit + CSP front door.
- The ER diagram regenerates from the models; the load profile and the
  backup/restore scripts run against a live stack.
- Backend and frontend gates (ruff, mypy, pytest, tsc, eslint, vitest, builds)
  all pass, and the end-to-end smoke (90 checks) still passes end to end.

With this, the six-phase build is complete: authentication and RBAC (1),
devices and crash ingestion (2), the crash-analysis engine (2.5), AI diagnosis
over a RAG knowledge base (3), the React web application (4), analytics/export/
alerting (5), and production hardening + CI/CD (6).
