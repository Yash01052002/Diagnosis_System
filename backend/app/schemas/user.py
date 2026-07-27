"""User and role schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field, field_validator

from app.core.config import settings
from app.schemas.common import BaseSchema

_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_DIGIT = re.compile(r"\d")
_SPECIAL = re.compile(r"[^A-Za-z0-9]")

Password = Annotated[str, Field(min_length=8, max_length=72)]


def validate_password_strength(value: str) -> str:
    """Enforce the platform password policy.

    Raises ``ValueError`` (rendered by FastAPI as a 422) when the password is
    too weak. Length is capped at 72 bytes because bcrypt truncates beyond it.
    """
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 bytes")
    missing = []
    if not _UPPER.search(value):
        missing.append("an uppercase letter")
    if not _LOWER.search(value):
        missing.append("a lowercase letter")
    if not _DIGIT.search(value):
        missing.append("a digit")
    if not _SPECIAL.search(value):
        missing.append("a special character")
    if missing:
        raise ValueError("Password must contain " + ", ".join(missing))
    return value


class RoleRead(BaseSchema):
    id: uuid.UUID
    name: str
    description: str | None = None


class UserBase(BaseSchema):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    """Self-service registration payload."""

    password: Password

    _check_password = field_validator("password")(validate_password_strength)


class UserAdminCreate(UserCreate):
    """Admin-side creation, which may assign roles and activation state."""

    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    is_active: bool = True
    is_verified: bool = False


class UserUpdate(BaseSchema):
    """Fields a user may change about themselves."""

    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None


class UserAdminUpdate(UserUpdate):
    """Fields only an administrator may change."""

    is_active: bool | None = None
    is_verified: bool | None = None
    roles: list[str] | None = None


class PasswordChange(BaseSchema):
    current_password: str
    new_password: Password

    _check_password = field_validator("new_password")(validate_password_strength)


class UserRead(UserBase):
    id: uuid.UUID
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleRead] = Field(default_factory=list)


class UserSummary(BaseSchema):
    """Lightweight projection used when embedding a user in other resources."""

    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
