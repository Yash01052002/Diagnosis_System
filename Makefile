# BlackBox developer shortcuts. Every target delegates to scripts/dev.sh or
# docker compose so behaviour is identical inside and outside make.

.DEFAULT_GOAL := help
.PHONY: help setup up down migrate seed seed-demo serve worker test coverage smoke lint fmt \
        build logs ps clean prod-up prod-down prod-logs backup restore er-diagram loadtest

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Create the backend venv and install dependencies
	@./scripts/dev.sh setup

up: ## Start postgres + redis
	@./scripts/dev.sh up

down: ## Stop all docker services
	@docker compose down

migrate: ## Apply database migrations
	@./scripts/dev.sh migrate

seed: ## Create default roles and the bootstrap admin
	@./scripts/dev.sh seed

seed-demo: ## Fill a running API with demo data (devices, crashes, KB, diagnoses)
	@cd backend && .venv/bin/python ../scripts/seed_demo.py $(ARGS)

serve: ## Run the API with autoreload
	@./scripts/dev.sh serve

worker: ## Run the Celery worker
	@./scripts/dev.sh worker

test: ## Run the backend test suite
	@./scripts/dev.sh test

coverage: ## Run the backend suite with the coverage gate
	@cd backend && .venv/bin/python -m pytest --cov=app --cov-report=term-missing

smoke: ## Run the end-to-end smoke test against a running API
	@./scripts/smoke.sh

lint: ## Run ruff and mypy
	@./scripts/dev.sh lint

fmt: ## Auto-format the backend
	@cd backend && .venv/bin/python -m ruff check --fix app tests alembic \
		&& .venv/bin/python -m ruff format app tests alembic

build: ## Build all docker images
	@docker compose build

logs: ## Tail the backend logs
	@docker compose logs -f backend

ps: ## Show container status
	@docker compose ps

clean: ## Remove containers, volumes and caches
	@docker compose down -v
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache backend/htmlcov

# -- Production & operations -------------------------------------------------
prod-up: ## Start the production stack (nginx edge + TLS)
	@docker compose -f docker-compose.prod.yml up -d --build

prod-down: ## Stop the production stack
	@docker compose -f docker-compose.prod.yml down

prod-logs: ## Tail the production edge + backend logs
	@docker compose -f docker-compose.prod.yml logs -f edge backend

backup: ## Back up the database (BACKUP_DIR overridable)
	@./scripts/backup.sh

restore: ## Restore the database from DUMP=path/to/file.dump
	@./scripts/restore.sh $(DUMP)

er-diagram: ## Regenerate the Mermaid ER diagram from the models
	@cd backend && .venv/bin/python scripts/generate_er_diagram.py

loadtest: ## Run the locust load test (needs BASE_URL + DEVICE_API_KEY)
	@cd backend && locust -f tests/load/locustfile.py --host "$${BASE_URL:-http://localhost:8000}"
