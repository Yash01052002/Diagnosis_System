#!/usr/bin/env bash
# Restore the BlackBox PostgreSQL database from a pg_dump custom-format file
# produced by backup.sh.
#
#   ./scripts/restore.sh backups/blackbox-20260731-120000.dump
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/restore.sh <dump> --force
#
# THIS OVERWRITES the current database (pg_restore --clean drops and recreates
# objects). It prompts before proceeding unless --force is passed.
set -euo pipefail

cd "$(dirname "$0")/.."

DUMP="${1:-}"
FORCE=0
[[ "${2:-}" == "--force" ]] && FORCE=1

if [[ -z "${DUMP}" || ! -f "${DUMP}" ]]; then
  echo "usage: $0 <dump-file> [--force]" >&2
  exit 2
fi

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DB_SERVICE="${DB_SERVICE:-db}"

# shellcheck disable=SC1091
[[ -f .env ]] && set -a && source .env && set +a
PG_USER="${POSTGRES_USER:-blackbox}"
PG_DB="${POSTGRES_DB:-blackbox}"

if (( ! FORCE )); then
  echo "About to OVERWRITE database '${PG_DB}' (service '${DB_SERVICE}') with:"
  echo "  ${DUMP}"
  read -r -p "Type the database name to confirm: " reply
  [[ "${reply}" == "${PG_DB}" ]] || { echo "aborted."; exit 1; }
fi

echo "[restore] restoring into '${PG_DB}'..."
# --clean --if-exists makes the restore idempotent; --no-owner avoids role
# mismatches between environments.
docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
  pg_restore --clean --if-exists --no-owner -U "${PG_USER}" -d "${PG_DB}" < "${DUMP}"

echo "[restore] done. Restart the backend so it picks up a clean connection pool:"
echo "  docker compose -f ${COMPOSE_FILE} restart backend worker beat"
