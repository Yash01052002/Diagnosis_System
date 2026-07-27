#!/usr/bin/env bash
# Local development helper.
#
#   ./scripts/dev.sh setup     create the venv and install dependencies
#   ./scripts/dev.sh up        start postgres + redis in docker
#   ./scripts/dev.sh migrate   apply database migrations
#   ./scripts/dev.sh seed      create default roles and the bootstrap admin
#   ./scripts/dev.sh serve     run the API with autoreload
#   ./scripts/dev.sh test      run the backend test suite
#   ./scripts/dev.sh lint      ruff + mypy
#   ./scripts/dev.sh smoke     end-to-end checks against a running API
#   ./scripts/dev.sh down      stop the docker services
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
VENV="${BACKEND_DIR}/.venv"
PY="${VENV}/bin/python"

ensure_env_file() {
  if [[ ! -f "${ROOT_DIR}/.env" ]]; then
    cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
    echo "created .env from .env.example"
  fi
  if [[ ! -f "${BACKEND_DIR}/.env" ]]; then
    ln -sf ../.env "${BACKEND_DIR}/.env"
  fi
}

ensure_venv() {
  [[ -x "${PY}" ]] || { echo "run './scripts/dev.sh setup' first" >&2; exit 1; }
}

case "${1:-help}" in
  setup)
    ensure_env_file
    if command -v uv >/dev/null 2>&1; then
      uv venv "${VENV}"
      uv pip install --python "${PY}" -e "${BACKEND_DIR}[dev]"
    else
      python3 -m venv "${VENV}"
      "${PY}" -m pip install --upgrade pip
      "${PY}" -m pip install -e "${BACKEND_DIR}[dev]"
    fi
    echo "setup complete"
    ;;
  up)
    ensure_env_file
    docker compose up -d db redis
    ;;
  migrate)
    ensure_venv
    cd "${BACKEND_DIR}" && "${VENV}/bin/alembic" upgrade head
    ;;
  seed)
    ensure_venv
    cd "${BACKEND_DIR}" && "${PY}" -m app.db.init_db
    ;;
  serve)
    ensure_venv
    cd "${BACKEND_DIR}" && "${VENV}/bin/uvicorn" app.main:app --reload --host 0.0.0.0 --port 8000
    ;;
  worker)
    ensure_venv
    cd "${BACKEND_DIR}" && "${VENV}/bin/celery" -A app.worker.celery_app worker --loglevel=INFO
    ;;
  test)
    ensure_venv
    cd "${BACKEND_DIR}" && "${PY}" -m pytest "${@:2}"
    ;;
  smoke)
    "${ROOT_DIR}/scripts/smoke.sh" "${@:2}"
    ;;
  lint)
    ensure_venv
    cd "${BACKEND_DIR}"
    "${PY}" -m ruff check app tests alembic
    "${PY}" -m ruff format --check app tests alembic
    "${PY}" -m mypy app
    ;;
  down)
    docker compose down
    ;;
  *)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
esac
