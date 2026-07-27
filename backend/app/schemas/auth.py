"""Authentication request/response schemas."""

from __future__ import annotations

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import BaseSchema
from app.schemas.user import Password, UserRead, validate_password_strength


class LoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseSchema):
    """OAuth2-style token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds")


class LoginResponse(TokenPair):
    user: UserRead


class RefreshRequest(BaseSchema):
    refresh_token: str


class LogoutRequest(BaseSchema):
    refresh_token: str | None = Field(
        default=None,
        description="Revoke this session only. Omit and set all_sessions to revoke everything.",
    )
    all_sessions: bool = False


class ForgotPasswordRequest(BaseSchema):
    email: EmailStr


class ResetPasswordRequest(BaseSchema):
    token: str = Field(min_length=16, max_length=256)
    new_password: Password

    _check_password = field_validator("new_password")(validate_password_strength)


class TokenPayload(BaseSchema):
    """Decoded JWT claims used internally."""

    sub: str
    type: str
    jti: str
    exp: int
    roles: list[str] = Field(default_factory=list)
