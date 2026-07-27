"""Exception handlers producing a single JSON error envelope.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _envelope(code: str, message: str, details: object | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return {"error": payload}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Render a domain error using its declared status code."""
    log = logger.warning if exc.status_code < 500 else logger.error
    log(
        "error.app",
        error_code=exc.error_code,
        status_code=exc.status_code,
        message=exc.message,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code, content=exc.to_dict(), headers=exc.headers or None
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Flatten FastAPI's validation errors into ``details.fields``."""
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_envelope(
            "validation_error", "The submitted payload failed validation.", {"fields": fields}
        ),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Wrap framework HTTP errors (404 routing, 405, ...) in the same envelope."""
    code = {
        401: "authentication_failed",
        403: "permission_denied",
        404: "not_found",
        405: "method_not_allowed",
        429: "rate_limited",
    }.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Translate a unique/foreign-key violation into 409 without leaking SQL."""
    logger.warning("error.integrity", path=request.url.path, error=str(exc.orig))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=_envelope(
            "conflict", "The request conflicts with the current state of the resource."
        ),
    )


async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Any other database failure is a 500; the detail stays in the logs."""
    logger.exception("error.database", path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope("database_error", "A database error occurred."),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler. Internals are only echoed outside production."""
    logger.exception("error.unhandled", path=request.url.path)
    message = (
        f"{type(exc).__name__}: {exc}"
        if not settings.is_production
        else "An unexpected error occurred."
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope("internal_error", message),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to ``app``."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, integrity_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
