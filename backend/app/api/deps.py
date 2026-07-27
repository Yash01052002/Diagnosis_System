"""FastAPI dependency wiring.

Everything the endpoints need is constructed here: repositories, services and
the authenticated principal. Endpoints depend on abstractions supplied by this
module rather than importing concrete implementations themselves.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import InactiveUserError, PermissionDeniedError, TokenError
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.user import RoleName, User
from app.repositories.audit_log import AuditLogRepository
from app.repositories.user import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
)
from app.schemas.common import PaginationParams
from app.services.audit import AuditService
from app.services.auth import AuthService, RequestContext
from app.services.email import EmailSender, get_email_sender
from app.services.user import UserService

#: ``auto_error=False`` so a missing header raises our own 401 envelope.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

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


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


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
