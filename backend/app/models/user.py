"""User, Role and authentication-token models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin


class RoleName(StrEnum):
    """Built-in roles. Kept as data (not a DB enum) so roles stay extensible."""

    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


#: Many-to-many association between users and roles.
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", GUID(), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named set of permissions granted to users."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list[User]] = relationship(
        secondary=user_roles, back_populates="roles", lazy="selectin"
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated principal of the platform."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )

    @property
    def role_names(self) -> list[str]:
        return sorted(role.name for role in self.roles)

    def has_role(self, *names: str) -> bool:
        granted = {role.name for role in self.roles}
        return any(name in granted for name in names)

    @property
    def is_admin(self) -> bool:
        return self.has_role(RoleName.ADMIN)


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A persisted refresh-token handle, enabling server-side revocation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("jti", name="uq_refresh_tokens_jti"),)

    jti: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="joined")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single-use, hashed password-reset token."""

    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="password_reset_tokens", lazy="joined")

    @property
    def is_used(self) -> bool:
        return self.used_at is not None
