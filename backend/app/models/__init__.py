"""ORM models.

Importing this package registers every model on ``Base.metadata`` which is
what Alembic autogenerate and the test fixtures rely on.
"""

from app.db.base import Base
from app.models.audit_log import AuditAction, AuditLog
from app.models.build import ArtifactType, BuildStatus, BuildSymbol, FirmwareBuild
from app.models.crash import CrashReport, CrashSeverity, CrashStatus, FaultType
from app.models.crash_group import CrashGroup, CrashGroupStatus
from app.models.device import Device, DeviceApiKey, DeviceStatus, Tag, device_tags
from app.models.diagnosis import AiDiagnosis, ConfidenceLabel
from app.models.document import (
    Document,
    DocumentChunk,
    DocumentSourceType,
    DocumentStatus,
)
from app.models.user import (
    PasswordResetToken,
    RefreshToken,
    Role,
    RoleName,
    User,
    user_roles,
)

__all__ = [
    "ArtifactType",
    "AuditAction",
    "AuditLog",
    "Base",
    "BuildStatus",
    "BuildSymbol",
    "CrashGroup",
    "CrashGroupStatus",
    "CrashReport",
    "CrashSeverity",
    "AiDiagnosis",
    "ConfidenceLabel",
    "CrashStatus",
    "Device",
    "Document",
    "DocumentChunk",
    "DocumentSourceType",
    "DocumentStatus",
    "DeviceApiKey",
    "DeviceStatus",
    "FaultType",
    "FirmwareBuild",
    "PasswordResetToken",
    "RefreshToken",
    "Role",
    "RoleName",
    "Tag",
    "User",
    "device_tags",
    "user_roles",
]
