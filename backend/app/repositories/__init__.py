"""Persistence layer (repository pattern)."""

from app.repositories.audit_log import AuditLogRepository
from app.repositories.base import BaseRepository, affected_rows
from app.repositories.crash import CrashReportRepository
from app.repositories.device import (
    DeviceApiKeyRepository,
    DeviceRepository,
    TagRepository,
)
from app.repositories.user import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
)

__all__ = [
    "AuditLogRepository",
    "BaseRepository",
    "CrashReportRepository",
    "DeviceApiKeyRepository",
    "DeviceRepository",
    "PasswordResetTokenRepository",
    "RefreshTokenRepository",
    "RoleRepository",
    "TagRepository",
    "UserRepository",
    "affected_rows",
]
