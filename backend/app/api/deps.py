"""FastAPI dependency wiring.

Everything the endpoints need is constructed here: repositories, services and
the authenticated principal. Endpoints depend on abstractions supplied by this
module rather than importing concrete implementations themselves.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import InactiveUserError, PermissionDeniedError, TokenError
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.device import Device
from app.models.user import RoleName, User
from app.repositories.analytics import AnalyticsRepository
from app.repositories.audit_log import AuditLogRepository
from app.repositories.build import BuildSymbolRepository, FirmwareBuildRepository
from app.repositories.crash import CrashReportRepository
from app.repositories.crash_group import CrashGroupRepository
from app.repositories.device import (
    DeviceApiKeyRepository,
    DeviceRepository,
    TagRepository,
)
from app.repositories.diagnosis import AiDiagnosisRepository
from app.repositories.document import DocumentChunkRepository, DocumentRepository
from app.repositories.notification import AlertSettingsRepository, NotificationRepository
from app.repositories.user import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
)
from app.schemas.common import PaginationParams
from app.services.ai.embeddings import get_embedding_provider
from app.services.ai.llm import get_llm_provider
from app.services.ai.vector_store import get_vector_store
from app.services.analytics import AnalyticsService
from app.services.audit import AuditService
from app.services.auth import AuthService, RequestContext
from app.services.build import BuildService
from app.services.crash import CrashService
from app.services.crash_parser import CrashParser, crash_parser
from app.services.device import DeviceService
from app.services.diagnosis import DiagnosisService
from app.services.email import EmailSender, get_email_sender
from app.services.knowledge_base import KnowledgeBaseService
from app.services.notifications import NotificationService
from app.services.symbolication import SymbolicationService
from app.services.user import UserService

#: ``auto_error=False`` so a missing header raises our own 401 envelope.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

#: Devices cannot perform an interactive login, so they present a long-lived
#: key instead of a JWT.
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, description="Device API key")

SessionDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------
def get_request_context(request: Request) -> RequestContext:
    """Extract client IP and user agent, honouring a reverse-proxy header."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return RequestContext(ip_address=ip, user_agent=request.headers.get("user-agent"))


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------
def get_user_repository(session: SessionDep) -> UserRepository:
    return UserRepository(session)


def get_role_repository(session: SessionDep) -> RoleRepository:
    return RoleRepository(session)


def get_refresh_token_repository(session: SessionDep) -> RefreshTokenRepository:
    return RefreshTokenRepository(session)


def get_reset_token_repository(session: SessionDep) -> PasswordResetTokenRepository:
    return PasswordResetTokenRepository(session)


def get_audit_repository(session: SessionDep) -> AuditLogRepository:
    return AuditLogRepository(session)


def get_device_repository(session: SessionDep) -> DeviceRepository:
    return DeviceRepository(session)


def get_tag_repository(session: SessionDep) -> TagRepository:
    return TagRepository(session)


def get_device_api_key_repository(session: SessionDep) -> DeviceApiKeyRepository:
    return DeviceApiKeyRepository(session)


def get_crash_repository(session: SessionDep) -> CrashReportRepository:
    return CrashReportRepository(session)


def get_build_repository(session: SessionDep) -> FirmwareBuildRepository:
    return FirmwareBuildRepository(session)


def get_build_symbol_repository(session: SessionDep) -> BuildSymbolRepository:
    return BuildSymbolRepository(session)


def get_crash_group_repository(session: SessionDep) -> CrashGroupRepository:
    return CrashGroupRepository(session)


def get_document_repository(session: SessionDep) -> DocumentRepository:
    return DocumentRepository(session)


def get_document_chunk_repository(session: SessionDep) -> DocumentChunkRepository:
    return DocumentChunkRepository(session)


def get_diagnosis_repository(session: SessionDep) -> AiDiagnosisRepository:
    return AiDiagnosisRepository(session)


def get_analytics_repository(session: SessionDep) -> AnalyticsRepository:
    return AnalyticsRepository(session)


def get_notification_repository(session: SessionDep) -> NotificationRepository:
    return NotificationRepository(session)


def get_alert_settings_repository(session: SessionDep) -> AlertSettingsRepository:
    return AlertSettingsRepository(session)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
def get_email_service(settings: SettingsDep) -> EmailSender:
    return get_email_sender(settings)


def get_audit_service(
    repository: Annotated[AuditLogRepository, Depends(get_audit_repository)],
) -> AuditService:
    return AuditService(repository)


def get_auth_service(
    session: SessionDep,
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    roles: Annotated[RoleRepository, Depends(get_role_repository)],
    refresh_tokens: Annotated[RefreshTokenRepository, Depends(get_refresh_token_repository)],
    reset_tokens: Annotated[PasswordResetTokenRepository, Depends(get_reset_token_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    email_sender: Annotated[EmailSender, Depends(get_email_service)],
) -> AuthService:
    return AuthService(
        session=session,
        users=users,
        roles=roles,
        refresh_tokens=refresh_tokens,
        reset_tokens=reset_tokens,
        audit=audit,
        email_sender=email_sender,
        settings=settings,
    )


def get_user_service(
    session: SessionDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    roles: Annotated[RoleRepository, Depends(get_role_repository)],
    refresh_tokens: Annotated[RefreshTokenRepository, Depends(get_refresh_token_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> UserService:
    return UserService(
        session=session,
        users=users,
        roles=roles,
        refresh_tokens=refresh_tokens,
        audit=audit,
    )


def get_crash_parser() -> CrashParser:
    """The parser is stateless, so a single instance is shared."""
    return crash_parser


def get_device_service(
    session: SessionDep,
    devices: Annotated[DeviceRepository, Depends(get_device_repository)],
    tags: Annotated[TagRepository, Depends(get_tag_repository)],
    api_keys: Annotated[DeviceApiKeyRepository, Depends(get_device_api_key_repository)],
    crashes: Annotated[CrashReportRepository, Depends(get_crash_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DeviceService:
    return DeviceService(
        session=session,
        devices=devices,
        tags=tags,
        api_keys=api_keys,
        crashes=crashes,
        audit=audit,
    )


def get_build_service(
    session: SessionDep,
    settings: SettingsDep,
    builds: Annotated[FirmwareBuildRepository, Depends(get_build_repository)],
    symbols: Annotated[BuildSymbolRepository, Depends(get_build_symbol_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> BuildService:
    return BuildService(
        session=session, builds=builds, symbols=symbols, audit=audit, settings=settings
    )


def get_symbolication_service(
    session: SessionDep,
    settings: SettingsDep,
    crashes: Annotated[CrashReportRepository, Depends(get_crash_repository)],
    builds: Annotated[FirmwareBuildRepository, Depends(get_build_repository)],
    symbols: Annotated[BuildSymbolRepository, Depends(get_build_symbol_repository)],
    groups: Annotated[CrashGroupRepository, Depends(get_crash_group_repository)],
) -> SymbolicationService:
    return SymbolicationService(
        session=session,
        crashes=crashes,
        builds=builds,
        symbols=symbols,
        groups=groups,
        settings=settings,
    )


def get_notification_service(
    session: SessionDep,
    settings: SettingsDep,
    notifications: Annotated[NotificationRepository, Depends(get_notification_repository)],
    alert_settings: Annotated[
        AlertSettingsRepository, Depends(get_alert_settings_repository)
    ],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    email_sender: Annotated[EmailSender, Depends(get_email_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> NotificationService:
    return NotificationService(
        session=session,
        notifications=notifications,
        alert_settings=alert_settings,
        users=users,
        email_sender=email_sender,
        audit=audit,
        settings=settings,
    )


def get_crash_service(
    session: SessionDep,
    crashes: Annotated[CrashReportRepository, Depends(get_crash_repository)],
    devices: Annotated[DeviceRepository, Depends(get_device_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    parser: Annotated[CrashParser, Depends(get_crash_parser)],
    symbolication: Annotated[SymbolicationService, Depends(get_symbolication_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
) -> CrashService:
    return CrashService(
        session=session,
        crashes=crashes,
        devices=devices,
        audit=audit,
        parser=parser,
        symbolication=symbolication,
        notifications=notifications,
    )


def get_knowledge_base_service(
    session: SessionDep,
    settings: SettingsDep,
    documents: Annotated[DocumentRepository, Depends(get_document_repository)],
    chunks: Annotated[DocumentChunkRepository, Depends(get_document_chunk_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> KnowledgeBaseService:
    embedder = get_embedding_provider(settings)
    return KnowledgeBaseService(
        session=session,
        documents=documents,
        chunks=chunks,
        embedder=embedder,
        vector_store=get_vector_store(session, settings),
        audit=audit,
        settings=settings,
    )


def get_diagnosis_service(
    session: SessionDep,
    settings: SettingsDep,
    crashes: Annotated[CrashReportRepository, Depends(get_crash_repository)],
    groups: Annotated[CrashGroupRepository, Depends(get_crash_group_repository)],
    diagnoses: Annotated[AiDiagnosisRepository, Depends(get_diagnosis_repository)],
    knowledge_base: Annotated[KnowledgeBaseService, Depends(get_knowledge_base_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DiagnosisService:
    return DiagnosisService(
        session=session,
        crashes=crashes,
        groups=groups,
        diagnoses=diagnoses,
        knowledge_base=knowledge_base,
        llm=get_llm_provider(settings),
        audit=audit,
        settings=settings,
    )


def get_analytics_service(
    settings: SettingsDep,
    analytics: Annotated[AnalyticsRepository, Depends(get_analytics_repository)],
) -> AnalyticsService:
    return AnalyticsService(analytics=analytics, settings=settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AnalyticsServiceDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
DeviceServiceDep = Annotated[DeviceService, Depends(get_device_service)]
CrashServiceDep = Annotated[CrashService, Depends(get_crash_service)]
BuildServiceDep = Annotated[BuildService, Depends(get_build_service)]
SymbolicationServiceDep = Annotated[SymbolicationService, Depends(get_symbolication_service)]
KnowledgeBaseServiceDep = Annotated[
    KnowledgeBaseService, Depends(get_knowledge_base_service)
]
DiagnosisServiceDep = Annotated[DiagnosisService, Depends(get_diagnosis_service)]


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> User:
    """Resolve the bearer token to an active user.

    Raises:
        TokenError: missing, malformed or expired token.
        InactiveUserError: the account was deactivated after the token was issued.
    """
    if credentials is None or not credentials.credentials:
        raise TokenError("Missing authentication credentials.")

    payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS, config=settings)
    try:
        user_id = payload["sub"]
    except KeyError as exc:  # pragma: no cover - decode_token already checks
        raise TokenError() from exc

    import uuid as _uuid

    try:
        user = await users.get_with_roles(_uuid.UUID(user_id))
    except ValueError as exc:
        raise TokenError("Malformed token subject.") from exc

    if user is None:
        raise TokenError("User no longer exists.")
    if not user.is_active:
        raise InactiveUserError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[[User], User]:
    """Build a dependency that allows only the given roles.

    Admins pass every check, so routes list the minimum roles they need::

        @router.post("/devices", dependencies=[Depends(require_roles("engineer"))])
    """
    allowed = {str(role) for role in roles}

    def dependency(current_user: CurrentUser) -> User:
        if current_user.is_admin or current_user.has_role(*allowed):
            return current_user
        raise PermissionDeniedError(
            "This action requires one of the following roles: " + ", ".join(sorted(allowed)),
            details={"required_roles": sorted(allowed)},
        )

    return dependency


async def get_current_device(
    api_key: Annotated[str | None, Depends(api_key_scheme)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> Device:
    """Resolve the ``X-API-Key`` header to a registered device."""
    if not api_key:
        raise TokenError("Missing device API key.")
    return await service.authenticate_api_key(api_key)


CurrentDevice = Annotated[Device, Depends(get_current_device)]


@dataclass(slots=True, frozen=True)
class IngestPrincipal:
    """Whoever submitted a crash report.

    Exactly one of ``device`` / ``user`` is set: a device authenticated with
    its API key, or an engineer submitting on its behalf with a JWT.
    """

    device: Device | None = None
    user: User | None = None


async def get_ingest_principal(
    api_key: Annotated[str | None, Depends(api_key_scheme)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> IngestPrincipal:
    """Authenticate a crash submission by device key or engineer JWT.

    The device key is checked first: it is the path firmware in the field
    takes, and it identifies the device without trusting the payload.
    """
    if api_key:
        return IngestPrincipal(device=await device_service.authenticate_api_key(api_key))

    if credentials and credentials.credentials:
        user = await get_current_user(credentials, settings, users)
        if not (user.is_admin or user.has_role(RoleName.ENGINEER)):
            raise PermissionDeniedError(
                "Submitting crash reports requires a device API key or the engineer role.",
                details={"required_roles": ["engineer"]},
            )
        return IngestPrincipal(user=user)

    raise TokenError("Provide a device API key in X-API-Key, or an engineer bearer token.")


IngestPrincipalDep = Annotated[IngestPrincipal, Depends(get_ingest_principal)]


#: Common role guards.
require_admin = require_roles(RoleName.ADMIN)
require_engineer = require_roles(RoleName.ENGINEER)
require_viewer = require_roles(RoleName.VIEWER, RoleName.ENGINEER)

AdminUser = Annotated[User, Depends(require_admin)]
EngineerUser = Annotated[User, Depends(require_engineer)]


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def get_pagination(page: int = 1, page_size: int = 20) -> PaginationParams:
    """Validated ``?page=&page_size=`` query parameters."""
    return PaginationParams(page=page, page_size=page_size)


PaginationDep = Annotated[PaginationParams, Depends(get_pagination)]
