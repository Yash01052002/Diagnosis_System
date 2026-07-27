"""Application error taxonomy.

Every failure raised by the service layer is an :class:`AppError`. The API
layer converts those into a single, predictable JSON envelope so clients never
have to parse framework-specific error shapes.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all domain/application errors."""

    status_code: int = 500
    error_code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.error_code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


class NotFoundError(AppError):
    status_code = 404
    error_code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = 409
    error_code = "conflict"
    message = "The resource already exists or conflicts with the current state."


class ValidationError(AppError):
    status_code = 422
    error_code = "validation_error"
    message = "The submitted payload failed validation."


class AuthenticationError(AppError):
    status_code = 401
    error_code = "authentication_failed"
    message = "Could not validate credentials."

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        headers = {"WWW-Authenticate": "Bearer"}
        headers.update(kwargs.pop("headers", {}) or {})
        super().__init__(message, headers=headers, **kwargs)


class InvalidCredentialsError(AuthenticationError):
    error_code = "invalid_credentials"
    message = "Incorrect email or password."


class InactiveUserError(AuthenticationError):
    status_code = 403
    error_code = "inactive_user"
    message = "This account is inactive. Contact an administrator."


class AccountLockedError(AuthenticationError):
    status_code = 423
    error_code = "account_locked"
    message = "Account temporarily locked after too many failed login attempts."


class PermissionDeniedError(AppError):
    status_code = 403
    error_code = "permission_denied"
    message = "You do not have permission to perform this action."


class TokenError(AuthenticationError):
    error_code = "invalid_token"
    message = "Token is invalid, expired or has been revoked."


class RateLimitError(AppError):
    status_code = 429
    error_code = "rate_limited"
    message = "Too many requests. Please try again later."
