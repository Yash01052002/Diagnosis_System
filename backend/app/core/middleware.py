"""HTTP middleware: request ids, access logging and security headers."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

Handler = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id and bind it to the logging context.

    Downstream log lines — including those emitted by services — automatically
    carry ``request_id``, which makes tracing a single request through the logs
    possible without threading an id through every call.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception("http.request_failed", duration_ms=duration_ms)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "http.request",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply conservative security headers to every response.

    HSTS is only emitted in production, where TLS terminates at Nginx; sending
    it over plain HTTP in development would pin developers to https://localhost.
    """

    def __init__(self, app: object, *, production: bool = False) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.production = production

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if self.production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
