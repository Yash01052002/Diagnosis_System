#!/usr/bin/env bash
# Back up the BlackBox PostgreSQL database (and, optionally, the artifact store)
# from a running Docker Compose stack.
#
#   ./scripts/backup.sh                       # dev stack (docker-compose.yml)
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/backup.sh
#   ./scripts/backup.sh --with-artifacts      # also archive the artifact volume
#
# Dumps go to ./backups/ as PostgreSQL custom-format files, which restore.sh
# reads with pg_restore. Keep this directory off the app servers in real
# deployments (ship to object storage).
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DB_SERVICE="${DB_SERVICE:-db}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
WITH_ARTIFACTS=0
[[ "${1:-}" == "--with-artifacts" ]] && WITH_ARTIFACTS=1

# Read DB credentials from .env if present, else fall back to the dev defaults.
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && source .env && set +a
PG_USER="${POSTGRES_USER:-blackbox}"
PG_DB="${POSTGRES_DB:-blackbox}"

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DUMP="${BACKUP_DIR}/blackbox-${STAMP}.dump"

echo "[backup] dumping database '${PG_DB}' from service '${DB_SERVICE}'..."
docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
  pg_dump -U "${PG_USER}" -d "${PG_DB}" -F c > "${DUMP}"
echo "[backup] wrote ${DUMP} ($(du -h "${DUMP}" | cut -f1))"

if (( WITH_ARTIFACTS )); then
  ART="${BACKUP_DIR}/artifacts-${STAMP}.tar.gz"
  echo "[backup] archiving the artifact volume..."
  # Mount the named volume read-only into a throwaway container and tar it out.
  VOLUME="$(docker compose -f "${COMPOSE_FILE}" config --volumes | grep -E 'artifact' | head -1)"
  PROJECT="$(docker compose -f "${COMPOSE_FILE}" config --format json 2>/dev/null | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
  docker run --rm \
    -v "${PROJECT:-blackbox}_${VOLUME:-artifact_data}:/data:ro" \
    -v "$(pwd)/${BACKUP_DIR}:/backup" \
    alpine tar czf "/backup/$(basename "${ART}")" -C /data . \
    && echo "[backup] wrote ${ART}" \
    || echo "[backup] artifact archive skipped (volume not found)"
fi

echo "[backup] done. Restore with: ./scripts/restore.sh ${DUMP}"
