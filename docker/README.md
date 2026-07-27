# Docker assets

Compose files live at the repository root; per-service build assets live next
to the service they belong to, because a Dockerfile can only copy from inside
its own build context.

| Asset | Location |
|---|---|
| Backend image | `backend/Dockerfile` |
| Backend entrypoint (wait-for-db, migrate, seed) | `backend/docker/entrypoint.sh` |
| PostgreSQL init SQL | `database/init/` |
| Frontend image *(Phase 4)* | `frontend/Dockerfile` |
| Nginx config *(Phase 6)* | `nginx/` |
| Production overrides *(Phase 6)* | `docker-compose.prod.yml` |
