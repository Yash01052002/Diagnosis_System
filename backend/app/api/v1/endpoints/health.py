"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import SessionDep, SettingsDep
from app.core.logging import get_logger
from app.schemas.common import HealthStatus, ReadinessStatus

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health(settings: SettingsDep) -> HealthStatus:
    """Return 200 whenever the process is running. Checks no dependencies."""
    return HealthStatus(status="ok", version=__version__, environment=settings.ENVIRONMENT)


@router.get(
    "/health/ready",
    response_model=ReadinessStatus,
    summary="Readiness probe",
    responses={503: {"model": ReadinessStatus, "description": "A dependency is unavailable"}},
)
async def readiness(
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
) -> ReadinessStatus:
    """Verify downstream dependencies. Returns 503 when any check fails."""
    checks: dict[str, str] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.error("health.database_unavailable", error=str(exc))
        checks["database"] = "error"

    checks["redis"] = await _check_redis(settings.REDIS_URL)

    # Only the database is required to serve traffic; Redis backs optional
    # background processing, so its absence is reported but not fatal.
    if checks["database"] == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    degraded = any(value == "error" for value in checks.values())

    return ReadinessStatus(
        status="degraded" if degraded else "ok",
        version=__version__,
        environment=settings.ENVIRONMENT,
        checks=checks,
    )


async def _check_redis(url: str) -> str:
    """Ping Redis. Reported as ``skipped`` when the client is not installed."""
    try:
        from redis.asyncio import Redis
    except ImportError:  # pragma: no cover - redis is a declared dependency
        return "skipped"

    client = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.ping()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.warning("health.redis_unavailable", error=str(exc))
        return "error"
    finally:
        await client.aclose()
