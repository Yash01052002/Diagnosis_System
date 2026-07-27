#!/usr/bin/env bash
# Container entrypoint: wait for PostgreSQL, apply migrations, seed, then exec
# the requested command.
set -euo pipefail

: "${POSTGRES_SERVER:=db}"
: "${POSTGRES_PORT:=5432}"
: "${RUN_MIGRATIONS:=true}"
: "${RUN_SEED:=true}"
: "${WAIT_FOR_DB_TIMEOUT:=60}"

wait_for_db() {
  echo "[entrypoint] waiting for postgres at ${POSTGRES_SERVER}:${POSTGRES_PORT}..."
  local deadline=$((SECONDS + WAIT_FOR_DB_TIMEOUT))
  until python - <<'PY'
import asyncio
import sys

from app.db.session import SessionFactory
from sqlalchemy import text


async def main() -> None:
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))


try:
    asyncio.run(main())
except Exception as exc:  # noqa: BLE001
    print(f"  not ready: {type(exc).__name__}", file=sys.stderr)
    sys.exit(1)
PY
  do
    if (( SECONDS >= deadline )); then
      echo "[entrypoint] database did not become ready in ${WAIT_FOR_DB_TIMEOUT}s" >&2
      exit 1
    fi
    sleep 2
  done
  echo "[entrypoint] database is ready"
}

wait_for_db

if [[ "${RUN_MIGRATIONS}" == "true" ]]; then
  echo "[entrypoint] applying migrations"
  alembic upgrade head
fi

if [[ "${RUN_SEED}" == "true" ]]; then
  echo "[entrypoint] seeding roles and bootstrap admin"
  python -m app.db.init_db
fi

echo "[entrypoint] starting: $*"
exec "$@"
