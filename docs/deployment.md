# Deployment guide

How to run BlackBox in production: a TLS-terminating nginx edge in front of the
API and the SPA, with PostgreSQL, Redis, a Celery worker and beat, all on a
private Docker network.

```
            :443
 Internet ───▶ edge (nginx)  ──/api,/health──▶ backend (uvicorn) ──▶ postgres
   TLS         rate limit    ──/──────────────▶ frontend (SPA)      └▶ redis ◀─ worker/beat
              sec headers
```

Only the **edge** publishes ports. PostgreSQL, Redis, the backend and the SPA
are reachable only inside the compose network.

## 1. Prerequisites

- A host with Docker Engine + the Compose plugin.
- A DNS record pointing at the host.
- Ports 80 and 443 reachable (80 is used for the HTTP→HTTPS redirect and ACME
  challenges).

## 2. Configure

```bash
git clone <repository-url> blackbox && cd blackbox
cp .env.example .env
```

Set at least these in `.env` — the stack refuses to start with the defaults:

| Variable | Notes |
|---|---|
| `ENVIRONMENT` | `production` (enables HSTS, disables debug) |
| `SECRET_KEY` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | a strong password |
| `FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD` | the bootstrap admin |
| `BACKEND_CORS_ORIGINS` | your public origin, e.g. `https://blackbox.example.com` |
| `FRONTEND_URL` | same origin — used to build password-reset links |
| `EMAIL_BACKEND` | `smtp` (+ `SMTP_*`) if you want password-reset and alert emails |

Phase 3/5 knobs (AI provider, alert threshold) have safe offline defaults; see
the comments in `.env.example`.

## 3. TLS certificates

The edge reads `./nginx/certs/fullchain.pem` and `./nginx/certs/privkey.pem`.

**Let's Encrypt (recommended).** Issue a certificate with certbot's webroot,
which the edge already serves under `/.well-known/acme-challenge/`:

```bash
mkdir -p nginx/certs
# Start the stack first so the edge can answer the HTTP-01 challenge.
docker compose -f docker-compose.prod.yml up -d --build

docker run --rm \
  -v "$(pwd)/nginx/certs:/etc/letsencrypt/live/blackbox" \
  -v blackbox-prod_certbot_web:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d blackbox.example.com --email you@example.com --agree-tos --no-eff-email
docker compose -f docker-compose.prod.yml restart edge
```

Renew on a cron (certbot `renew`, then `docker compose ... restart edge`).

**Testing only.** A self-signed pair works for a smoke of the TLS path:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout nginx/certs/privkey.pem -out nginx/certs/fullchain.pem \
  -subj "/CN=localhost"
```

## 4. Start

```bash
make prod-up            # docker compose -f docker-compose.prod.yml up -d --build
```

The backend entrypoint waits for PostgreSQL, applies Alembic migrations, and
seeds the roles + bootstrap admin. Watch it come up:

```bash
make prod-logs          # tails edge + backend
curl -k https://localhost/health
```

Then browse to `https://blackbox.example.com` and sign in as the bootstrap
admin. **Change `FIRST_SUPERUSER_PASSWORD` before exposing the host.**

## 5. Hardening that's already on

- **TLS** terminated at the edge (TLS 1.2/1.3, modern ciphers, no session
  tickets), with HSTS.
- **Rate limiting**: `20 r/s` on `/api/`, `5 r/min` on `/api/v1/auth/` (burst
  allowances tuned for a login form, not a brute-force script) — returns `429`.
- **Security headers** at both the edge and the app: HSTS, `X-Frame-Options:
  DENY`, `nosniff`, a strict `Content-Security-Policy` (`script-src 'self'`,
  no inline scripts), `Referrer-Policy`, `Permissions-Policy`.
- **Least privilege**: the backend image runs as a non-root user; the database
  and Redis are not exposed to the host.
- **Auth**: bcrypt, refresh-token rotation with server-side revocation, account
  lockout — see the [README security section](../README.md#security).

## 6. Upgrades

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build   # entrypoint runs migrations
```

Migrations run automatically on backend start (`RUN_MIGRATIONS=true`). To apply
them by hand instead: `docker compose -f docker-compose.prod.yml run --rm
backend alembic upgrade head`.

## 7. Backups & restore

See [operations/backup-restore.md](operations/backup-restore.md). In short:

```bash
COMPOSE_FILE=docker-compose.prod.yml make backup            # → ./backups/*.dump
COMPOSE_FILE=docker-compose.prod.yml make restore DUMP=backups/<file>.dump
```

## 8. Health & monitoring

- `GET /health` — liveness (edge proxies it, access-log off).
- `GET /health/ready` — readiness with per-dependency checks (PostgreSQL,
  Redis). Wire this to your orchestrator's readiness probe.
- Logs are structured JSON in production (`LOG_JSON=true`) with a request id on
  every line — ship them to your log stack.
- The audit log (`GET /api/v1/audit-logs`, admin) is the system of record for
  privileged actions.

## 9. Scaling notes

- The backend is stateless; run more replicas behind the edge (`deploy.replicas`
  or multiple hosts + a real load balancer). Set `real_ip_header` / trusted
  proxies to match your LB so rate limiting and audit IPs stay correct.
- Redis + Celery already absorb out-of-band work (symbolization,
  re-diagnosis, alert email). Scale workers with `--concurrency` or more
  `worker` replicas.
- PostgreSQL is the one stateful tier — use managed Postgres or a replicated
  setup and point `DATABASE_URL` at it (then drop the `db` service).
- Load-test a candidate before rollout: `make loadtest` (see
  `backend/tests/load/locustfile.py`).
