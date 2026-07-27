"""ORM models.

Importing this package registers every model on ``Base.metadata`` which is
what Alembic autogenerate and the test fixtures rely on.
"""

from app.db.base import Base
from app.models.audit_log import AuditAction, AuditLog
from app.models.crash import CrashReport, CrashSeverity, CrashStatus, FaultType
from app.models.device import Device, DeviceApiKey, DeviceStatus, Tag, device_tags
from app.models.user import (
    PasswordResetToken,
    RefreshToken,
    Role,
    RoleName,
    User,
    user_roles,
)

__all__ = [
    "AuditAction",
    "AuditLog",
    "Base",
    "CrashReport",
    "CrashSeverity",
    "CrashStatus",
    "Device",
    "DeviceApiKey",
    "DeviceStatus",
    "FaultType",
    "PasswordResetToken",
    "RefreshToken",
    "Role",
    "RoleName",
    "Tag",
    "User",
    "device_tags",
    "user_roles",
]
