"""Application factory and ASGI entrypoint.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app import __version__
from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.session import dispose_engine

logger = get_logger(__name__)

DESCRIPTION = """
**BlackBox** is an AI-powered crash diagnosis system for embedded firmware
(STM32 + FreeRTOS). Devices in the field submit crash reports; the platform
stores, symbolizes and diagnoses them, then presents the results in a
dashboard.

### Authentication
Obtain a token pair from `POST /api/v1/auth/login` and send it as
`Authorization: Bearer <access_token>`. Access tokens are short-lived; rotate
them with `POST /api/v1/auth/refresh`.

### Roles
| Role | Capability |
|---|---|
| `admin` | Full access, including user management and the audit trail |
| `engineer` | Manage devices and crash reports, trigger diagnoses |
| `viewer` | Read-only access to dashboards and crash history |
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks."""
    settings = get_settings()
    logger.info(
        "app.startup",
        version=__version__,
        environment=settings.ENVIRONMENT,
        docs_enabled=not settings.is_production,
    )
    yield
    await dispose_engine()
    logger.info("app.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Exposed as a factory so tests can construct isolated instances with
    overridden settings.
    """
    config = settings or get_settings()
    configure_logging(config)

    app = FastAPI(
        title=config.PROJECT_NAME,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        # Interactive docs are disabled in production; the schema is still
        # generated and can be published from CI.
        docs_url=None if config.is_production else "/docs",
        redoc_url=None if config.is_production else "/redoc",
        openapi_url=None if config.is_production else "/openapi.json",
        contact={"name": "BlackBox Platform Team"},
        license_info={"name": "MIT"},
    )

    # Middleware is applied bottom-up: security headers wrap the request-context
    # logger so that even error responses carry both.
    app.add_middleware(SecurityHeadersMiddleware, production=config.is_production)
    app.add_middleware(RequestContextMiddleware)
    if config.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in config.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    register_exception_handlers(app)

    app.include_router(health.router)  # unversioned probes for orchestrators
    app.include_router(api_router, prefix=config.API_V1_PREFIX)

    app.openapi = _custom_openapi(app)  # type: ignore[method-assign]
    return app


def _custom_openapi(app: FastAPI):  # type: ignore[no-untyped-def]
    """Cache the schema and declare the bearer security scheme once."""

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        schema["tags"] = [
            {"name": "Health", "description": "Liveness and readiness probes"},
            {"name": "Authentication", "description": "Registration, login and passwords"},
            {"name": "Users", "description": "User and role administration"},
            {"name": "Audit", "description": "Security audit trail"},
        ]
        app.openapi_schema = schema
        return schema

    return openapi


app = create_app()
