# Phase 1 — Foundation, Authentication and RBAC

## Objectives

1. A monorepo skeleton that later phases slot into without restructuring.
2. A FastAPI service with clean-architecture layering: API → service →
   repository → model.
3. PostgreSQL schema with versioned Alembic migrations.
4. JWT authentication with refresh-token rotation and server-side revocation.
5. Role-based access control for `admin` / `engineer` / `viewer`.
6. Password reset by email, account lockout and an audit trail.
7. Docker Compose stack, health checks, structured logging.
8. Automated tests covering the security rules.

## Layering

```
HTTP request
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ API layer            app/api/v1/endpoints/*.py              │
│ HTTP concerns only: routing, status codes, OpenAPI metadata │
│ Dependencies (app/api/deps.py) inject everything below      │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ Service layer        app/services/*.py                      │
│ Business rules: lockout policy, token rotation, role guards │
│ Owns the transaction boundary (commit / rollback)           │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ Repository layer     app/repositories/*.py                  │
│ All SQL lives here. Services never build queries            │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ Model layer          app/models/*.py    (SQLAlchemy 2.0)    │
└─────────────────────────────────────────────────────────────┘
```

Why this shape:

- **Testability** — services take their collaborators as constructor
  arguments, so `AuthService` can be tested with fake repositories and the
  in-memory email sender.
- **Swappability** — `EmailSender` is an ABC with console/SMTP/in-memory
  implementations. Phase 3 adds `LLMProvider` the same way, which is what makes
  "OpenAI now, local model later" a configuration change.
- **One place per rule** — the lockout threshold is enforced in
  `AuthService._register_failed_attempt` and nowhere else.

## Request lifecycle

```
Client
  │  Authorization: Bearer <access_token>
  ▼
SecurityHeadersMiddleware   adds nosniff / DENY / HSTS(prod)
  ▼
RequestContextMiddleware    assigns X-Request-ID, binds it to structlog
  ▼
CORSMiddleware
  ▼
Route dependencies
  ├── get_db              → AsyncSession (rolled back on exception)
  ├── get_current_user    → decode JWT, load user, reject if inactive
  └── require_roles(...)  → 403 unless the user holds an allowed role
  ▼
Endpoint → Service → Repository → PostgreSQL
  ▼
Exception handlers → {"error": {"code", "message", "details"}}
```

## Data model

```
┌───────────────┐        ┌──────────────┐        ┌───────────────┐
│    users      │───┬───<│  user_roles  │>───┬───│     roles     │
├───────────────┤   │    ├──────────────┤    │   ├───────────────┤
│ id (uuid) PK  │   │    │ user_id  FK  │    │   │ id (uuid) PK  │
│ email      UQ │   │    │ role_id  FK  │    │   │ name       UQ │
│ full_name     │   │    └──────────────┘    │   │ description   │
│ hashed_pw     │   │                        │   └───────────────┘
│ is_active     │   │                        │
│ is_verified   │   │   admin / engineer / viewer
│ last_login_at │   │
│ failed_logins │   │
│ locked_until  │   │
└───────┬───────┘   │
        │           │
        │ 1:N       │ 1:N
        ▼           ▼
┌──────────────────┐  ┌─────────────────────────┐  ┌────────────────┐
│ refresh_tokens   │  │ password_reset_tokens   │  │  audit_logs    │
├──────────────────┤  ├─────────────────────────┤  ├────────────────┤
│ id          PK   │  │ id                 PK   │  │ id         PK  │
│ jti         UQ   │  │ token_hash        IDX   │  │ action    IDX  │
│ user_id     FK   │  │ user_id            FK   │  │ actor_id   FK  │
│ expires_at       │  │ expires_at              │  │ actor_email    │
│ revoked_at       │  │ used_at                 │  │ resource_type  │
│ user_agent       │  └─────────────────────────┘  │ resource_id    │
│ ip_address       │                               │ ip_address     │
└──────────────────┘                               │ success        │
                                                   │ context JSONB  │
                                                   └────────────────┘
```

Design notes:

- **UUID primary keys** — crash reports arrive from many devices and will be
  ingested in parallel; UUIDs avoid a central sequence and stop record counts
  leaking through sequential ids.
- **Roles as rows, not an enum** — adding a role later is an INSERT, not a
  migration that rewrites a type.
- **`refresh_tokens` stores only the `jti`**, never the token itself. Logout
  and "revoke all sessions" work by flipping `revoked_at`.
- **`password_reset_tokens` stores a SHA-256 hash.** The plaintext exists only
  in the email. SHA-256 (not bcrypt) is correct here because the token already
  carries 256 bits of entropy and lookups must be fast.
- **`audit_logs` is append-only.** Nothing in the application updates or
  deletes a row; `actor_id` is `ON DELETE SET NULL` so deleting a user does not
  erase their history.

## Security decisions

| Threat | Mitigation |
|---|---|
| Password cracking | bcrypt with per-password salt; ≥10 chars, mixed classes |
| Brute force | Lockout after N failures for `ACCOUNT_LOCKOUT_MINUTES` |
| User enumeration on login | Unknown email and wrong password both return the same 401; a dummy hash is computed so timing matches |
| User enumeration on reset | `forgot-password` always returns the same message |
| Stolen refresh token | Rotation on every refresh — a replayed token is rejected |
| Stolen access token after deactivation | `get_current_user` re-checks `is_active` on every request |
| Compromised account | Password reset and change revoke all sessions |
| Privilege escalation | `roles` is only honoured on admin routes; ignored by `PATCH /users/me` |
| Admin lockout | An admin cannot remove their own admin role or delete themselves |
| Leaking internals | Errors are mapped to a fixed envelope; tracebacks only outside production |
| Clickjacking / MIME sniffing | Security headers on every response |

## Phase 1 file map

| Path | Responsibility |
|---|---|
| `app/main.py` | App factory, middleware, routers, OpenAPI customisation |
| `app/core/config.py` | Env-driven settings, cached singleton, computed DSNs |
| `app/core/security.py` | bcrypt hashing, JWT mint/decode, opaque tokens |
| `app/core/exceptions.py` | Error taxonomy mapped to status codes |
| `app/core/error_handlers.py` | Exception → JSON envelope |
| `app/core/middleware.py` | Request id + access log, security headers |
| `app/core/logging.py` | structlog configuration (JSON in prod) |
| `app/db/base.py` | Declarative base, UUID/JSON types, timestamp mixin |
| `app/db/session.py` | Async engine, session factory, `get_db` dependency |
| `app/db/init_db.py` | Idempotent seeding of roles + bootstrap admin |
| `app/models/user.py` | `User`, `Role`, `RefreshToken`, `PasswordResetToken` |
| `app/models/audit_log.py` | `AuditLog` + `AuditAction` vocabulary |
| `app/schemas/*` | Request/response contracts and password policy |
| `app/repositories/*` | All SQL, per aggregate |
| `app/services/auth.py` | Registration, login, refresh, logout, reset |
| `app/services/user.py` | User CRUD, role assignment, guards |
| `app/services/email.py` | `EmailSender` ABC + console/SMTP/in-memory |
| `app/services/audit.py` | Audit event recording |
| `app/api/deps.py` | Dependency wiring, `get_current_user`, `require_roles` |
| `app/api/v1/endpoints/*` | auth, users, audit, health routes |
| `app/worker.py` | Celery app + token-purge beat task |
| `alembic/versions/0001_*` | Initial schema and role seed |

## What Phase 2 builds on

- `require_roles("engineer")` already exists — device and crash endpoints just
  declare it.
- `BaseRepository` gives `DeviceRepository` and `CrashRepository` their CRUD.
- `AuditAction` gains `device.*` and `crash.*` members; the table is unchanged.
- `app/worker.py` is where crash-ingestion and diagnosis tasks are registered.
- The `Page[T]` schema is reused by every future list endpoint.
