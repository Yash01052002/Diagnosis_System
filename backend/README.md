# BlackBox Backend

FastAPI service for the BlackBox crash diagnosis platform. See the
[repository README](../README.md) for the full project overview and
[`docs/architecture/phase-1.md`](../docs/architecture/phase-1.md) for the
design rationale.

## Layout

```
app/
├── api/           HTTP layer — routes and dependency wiring
│   ├── deps.py    sessions, services, get_current_user, require_roles
│   └── v1/        versioned endpoints: auth, users, audit, health
├── core/          config, security, logging, exceptions, middleware
├── db/            engine, session, declarative base, seeding
├── models/        SQLAlchemy 2.0 models
├── repositories/  all SQL — services never build queries
├── schemas/       Pydantic request/response contracts
├── services/      business rules and transaction boundaries
├── main.py        application factory
└── worker.py      Celery app and scheduled tasks
```

## Development

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

.venv/bin/alembic upgrade head          # migrations
.venv/bin/python -m app.db.init_db      # roles + bootstrap admin
.venv/bin/uvicorn app.main:app --reload # http://localhost:8000/docs
```

## Quality gates

```bash
.venv/bin/python -m pytest              # 76 tests, in-memory SQLite
.venv/bin/python -m pytest --cov=app --cov-report=term-missing
.venv/bin/python -m ruff check app tests alembic
.venv/bin/python -m ruff format --check app tests alembic
.venv/bin/python -m mypy app
```

## Conventions

- **Async everywhere.** All database access is async; a lazy relationship load
  during serialization raises `MissingGreenlet`, so relationships that a schema
  reads are eager-loaded (`lazy="selectin"` or an explicit `selectinload`).
- **Services own transactions.** Repositories `flush`, services `commit`.
  An audit entry is written in the same transaction as the action it records.
- **Errors are domain objects.** Raise `AppError` subclasses from services;
  the API layer never builds an `HTTPException`.
- **Configuration is injected.** Take `Settings` as an argument rather than
  importing the module-level singleton, so tests can override it.
