# Backup & restore runbook

BlackBox keeps two kinds of durable state:

1. **PostgreSQL** — users, devices, crashes, groups, diagnoses, documents and
   their embeddings, notifications, the audit log. This is the source of truth.
2. **The artifact store** — uploaded firmware ELF/MAP files (a Docker volume,
   `artifact_data`). Symbols are in the database; these files are only needed to
   resolve *source lines* for crashes, and can be re-uploaded, so they are a
   lower backup priority than the database.

The knowledge-base vectors live **in the database** (Phase 3, database vector
store), so a database backup captures the RAG corpus too.

## Back up

`scripts/backup.sh` runs `pg_dump` inside the `db` container and writes a
PostgreSQL custom-format dump to `./backups/`.

```bash
# Dev stack
make backup

# Production stack
COMPOSE_FILE=docker-compose.prod.yml ./scripts/backup.sh

# Also archive the artifact volume
COMPOSE_FILE=docker-compose.prod.yml ./scripts/backup.sh --with-artifacts
```

Output:

```
backups/blackbox-20260731-120000.dump      # database (custom format)
backups/artifacts-20260731-120000.tar.gz   # only with --with-artifacts
```

**Ship dumps off the host.** `./backups/` on the same machine survives an app
crash, not a disk loss — copy to object storage (S3/GCS) and keep a retention
window (e.g. 7 daily + 4 weekly).

Suggested schedule (host cron):

```cron
# 02:15 every day
15 2 * * *  cd /opt/blackbox && COMPOSE_FILE=docker-compose.prod.yml ./scripts/backup.sh >> /var/log/blackbox-backup.log 2>&1
```

## Restore

`scripts/restore.sh` restores a dump with `pg_restore --clean --if-exists`, so
it is idempotent and replaces current objects. **It overwrites the database** and
prompts for confirmation unless `--force` is given.

```bash
# Production
COMPOSE_FILE=docker-compose.prod.yml ./scripts/restore.sh backups/blackbox-20260731-120000.dump

# Non-interactive (e.g. in a DR script)
COMPOSE_FILE=docker-compose.prod.yml ./scripts/restore.sh backups/<file>.dump --force
```

After a restore, bounce the app so it opens a fresh connection pool:

```bash
docker compose -f docker-compose.prod.yml restart backend worker beat
```

### Restore the artifact volume (if archived)

```bash
docker run --rm \
  -v blackbox-prod_artifact_data:/data \
  -v "$(pwd)/backups:/backup" \
  alpine sh -c "cd /data && tar xzf /backup/artifacts-<stamp>.tar.gz"
```

## Verify a backup

A backup you haven't restored is a hope, not a backup. Periodically restore the
latest dump into a throwaway stack and check it boots:

```bash
# In a scratch copy of the repo, with its own .env
./scripts/restore.sh backups/<file>.dump --force
docker compose up -d backend
curl -s localhost:8000/health/ready | jq   # database: ok
```

## Disaster recovery outline

1. Provision a fresh host with Docker + the repo + `.env` + TLS certs.
2. `make prod-up` — starts the stack; the backend runs migrations against the
   (empty) database.
3. `./scripts/restore.sh <latest-dump> --force` — load the data.
4. Restore the artifact archive if you keep one.
5. `docker compose -f docker-compose.prod.yml restart backend worker beat`.
6. Smoke it: sign in, open the dashboard, check `/health/ready`.

Recovery time is dominated by image build + dump size; recovery point is your
backup interval (hourly/daily as configured above).
