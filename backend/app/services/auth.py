"""Authentication service: registration, login, refresh, logout, password reset.

All security policy lives here (lockout, token rotation, reset-token single
use). The API layer only translates HTTP to these calls, which keeps the rules
testable without a web server.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    AccountLockedError,
    ConflictError,
    InactiveUserError,
    InvalidCredentialsError,
    TokenError,
)
from app.core.logging import get_logger
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.audit_log import AuditAction
from app.models.user import PasswordResetToken, RefreshToken, RoleName, User
from app.repositories.user import (
    PasswordResetTokenRepository,
    RefreshTokenRepository,
    RoleRepository,
    UserRepository,
)
from app.schemas.auth import TokenPair
from app.services.audit import AuditService
from app.services.email import EmailSender, build_password_reset_email

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class RequestContext:
    """Client metadata attached to audit entries and sessions."""

    ip_address: str | None = None
    user_agent: str | None = None


class AuthService:
    """Use-cases for authentication and credential management."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        users: UserRepository,
        roles: RoleRepository,
        refresh_tokens: RefreshTokenRepository,
        reset_tokens: PasswordResetTokenRepository,
        audit: AuditService,
        email_sender: EmailSender,
        settings: Settings,
    ) -> None:
        self.session = session
        self.users = users
        self.roles = roles
        self.refresh_tokens = refresh_tokens
        self.reset_tokens = reset_tokens
        self.audit = audit
        self.email_sender = email_sender
        self.settings = settings

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None = None,
        ctx: RequestContext | None = None,
    ) -> User:
        """Create a self-service account with the default ``viewer`` role."""
        ctx = ctx or RequestContext()
        normalized = UserRepository.normalize_email(email)

        if await self.users.email_exists(normalized):
            raise ConflictError("An account with this email already exists.")

        user = User(
            email=normalized,
            full_name=full_name,
            hashed_password=hash_password(password),
            is_active=True,
            is_verified=False,
        )
        default_role = await self.roles.get_by_name(RoleName.VIEWER)
        if default_role is not None:
            user.roles.append(default_role)

        self.users.add(user)
        await self.session.flush()

        await self.audit.record(
            AuditAction.USER_REGISTERED,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        await self.session.commit()
        await self.session.refresh(user, attribute_names=["roles"])
        logger.info("auth.registered", user_id=str(user.id), email=user.email)
        return user

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        ctx: RequestContext | None = None,
    ) -> tuple[User, TokenPair]:
        """Verify credentials and issue an access/refresh token pair.

        Raises:
            InvalidCredentialsError: unknown email or wrong password.
            AccountLockedError: too many recent failures.
            InactiveUserError: the account has been deactivated.
        """
        ctx = ctx or RequestContext()
        user = await self.users.get_by_email(email)

        if user is None:
            # Hash a dummy password so response time does not reveal whether
            # the account exists (user enumeration defence).
            verify_password(password, hash_password("dummy-password-for-timing"))
            await self._record_failed_login(None, email, ctx, reason="unknown_email")
            await self.session.commit()
            raise InvalidCredentialsError()

        if self._is_locked(user):
            await self._record_failed_login(user.id, user.email, ctx, reason="locked")
            await self.session.commit()
            raise AccountLockedError()

        if not verify_password(password, user.hashed_password):
            await self._register_failed_attempt(user, ctx)
            await self.session.commit()
            raise InvalidCredentialsError()

        if not user.is_active:
            await self._record_failed_login(user.id, user.email, ctx, reason="inactive")
            await self.session.commit()
            raise InactiveUserError()

        # Successful login: clear lockout state and opportunistically upgrade
        # the password hash if bcrypt parameters have changed.
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(UTC)
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)

        tokens = await self._issue_tokens(user, ctx)

        await self.audit.record(
            AuditAction.USER_LOGIN,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        await self.session.commit()
        logger.info("auth.login", user_id=str(user.id))
        return user, tokens

    # ------------------------------------------------------------------
    # Refresh / logout
    # ------------------------------------------------------------------
    async def refresh(self, refresh_token: str, ctx: RequestContext | None = None) -> TokenPair:
        """Rotate a refresh token, revoking the presented one.

        Rotation means a stolen token is usable at most once, and reuse of an
        already-rotated token is rejected.
        """
        ctx = ctx or RequestContext()
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH, config=self.settings)
        stored = await self.refresh_tokens.get_active_by_jti(payload["jti"])
        if stored is None:
            raise TokenError("Refresh token is invalid, expired or already used.")

        user = await self.users.get_with_roles(stored.user_id)
        if user is None or not user.is_active:
            await self.refresh_tokens.revoke(stored)
            await self.session.commit()
            raise InactiveUserError()

        await self.refresh_tokens.revoke(stored)
        tokens = await self._issue_tokens(user, ctx)

        await self.audit.record(
            AuditAction.TOKEN_REFRESHED,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        await self.session.commit()
        return tokens

    async def logout(
        self,
        *,
        user: User,
        refresh_token: str | None = None,
        all_sessions: bool = False,
        ctx: RequestContext | None = None,
    ) -> int:
        """Revoke one session or every session for ``user``.

        Returns the number of sessions revoked. Logout is idempotent: an
        already-revoked or unparsable token is not an error.
        """
        ctx = ctx or RequestContext()
        revoked = 0

        if all_sessions:
            revoked = await self.refresh_tokens.revoke_all_for_user(user.id)
        elif refresh_token:
            try:
                payload = decode_token(
                    refresh_token, expected_type=TokenType.REFRESH, config=self.settings
                )
            except TokenError:
                payload = None
            if payload is not None:
                stored = await self.refresh_tokens.get_by_jti(payload["jti"])
                # Only the owner may revoke a session.
                if stored is not None and stored.user_id == user.id and not stored.is_revoked:
                    await self.refresh_tokens.revoke(stored)
                    revoked = 1

        await self.audit.record(
            AuditAction.USER_LOGOUT,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"all_sessions": all_sessions, "revoked": revoked},
        )
        await self.session.commit()
        return revoked

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------
    async def request_password_reset(
        self, email: str, ctx: RequestContext | None = None
    ) -> str | None:
        """Issue a password-reset token and email it to the user.

        Always succeeds from the caller's point of view so the endpoint cannot
        be used to discover which emails are registered. Returns the plaintext
        token when one was issued (tests and console backend only).
        """
        ctx = ctx or RequestContext()
        user = await self.users.get_by_email(email)

        if user is None or not user.is_active:
            await self.audit.record(
                AuditAction.PASSWORD_RESET_REQUESTED,
                actor_email=UserRepository.normalize_email(email),
                ip_address=ctx.ip_address,
                user_agent=ctx.user_agent,
                success=False,
                context={"reason": "unknown_or_inactive"},
            )
            await self.session.commit()
            logger.info("auth.password_reset.ignored", email=email)
            return None

        # Outstanding tokens are invalidated so only the newest link works.
        await self.reset_tokens.invalidate_for_user(user.id)

        plaintext = generate_opaque_token()
        record = PasswordResetToken(
            token_hash=hash_opaque_token(plaintext),
            user_id=user.id,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=self.settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )
        self.reset_tokens.add(record)

        await self.audit.record(
            AuditAction.PASSWORD_RESET_REQUESTED,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        await self.session.commit()

        self.email_sender.send(
            build_password_reset_email(to=user.email, token=plaintext, config=self.settings)
        )
        return plaintext

    async def reset_password(
        self, *, token: str, new_password: str, ctx: RequestContext | None = None
    ) -> User:
        """Consume a reset token and set a new password.

        Every existing session is revoked so a stolen refresh token cannot
        survive the reset.
        """
        ctx = ctx or RequestContext()
        record = await self.reset_tokens.get_active_by_hash(hash_opaque_token(token))
        if record is None:
            raise TokenError("Password reset link is invalid or has expired.")

        user = await self.users.get_with_roles(record.user_id)
        if user is None or not user.is_active:
            raise InactiveUserError()

        user.hashed_password = hash_password(new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        record.used_at = datetime.now(UTC)
        await self.refresh_tokens.revoke_all_for_user(user.id)

        await self.audit.record(
            AuditAction.PASSWORD_RESET_COMPLETED,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        await self.session.commit()
        logger.info("auth.password_reset.completed", user_id=str(user.id))
        return user

    async def change_password(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
        ctx: RequestContext | None = None,
    ) -> User:
        """Change the password of an authenticated user."""
        ctx = ctx or RequestContext()
        if not verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError("Current password is incorrect.")

        user.hashed_password = hash_password(new_password)
        await self.refresh_tokens.revoke_all_for_user(user.id)

        await self.audit.record(
            AuditAction.PASSWORD_CHANGED,
            actor_id=user.id,
            actor_email=user.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        await self.session.commit()
        return user

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _issue_tokens(self, user: User, ctx: RequestContext) -> TokenPair:
        """Mint an access token and a persisted refresh token."""
        access_token, _, _ = create_access_token(
            str(user.id), roles=user.role_names, config=self.settings
        )
        refresh_token, jti, expires_at = create_refresh_token(str(user.id), config=self.settings)
        self.refresh_tokens.add(
            RefreshToken(
                jti=jti,
                user_id=user.id,
                expires_at=expires_at,
                user_agent=ctx.user_agent[:255] if ctx.user_agent else None,
                ip_address=ctx.ip_address,
            )
        )
        await self.session.flush()
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    def _is_locked(self, user: User) -> bool:
        if user.locked_until is None:
            return False
        locked_until = user.locked_until
        if locked_until.tzinfo is None:  # SQLite returns naive datetimes
            locked_until = locked_until.replace(tzinfo=UTC)
        return locked_until > datetime.now(UTC)

    async def _register_failed_attempt(self, user: User, ctx: RequestContext) -> None:
        """Increment the failure counter and lock the account at the threshold."""
        user.failed_login_attempts += 1
        reason = "bad_password"
        if user.failed_login_attempts >= self.settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(UTC) + timedelta(
                minutes=self.settings.ACCOUNT_LOCKOUT_MINUTES
            )
            user.failed_login_attempts = 0
            reason = "locked"
            await self.audit.record(
                AuditAction.USER_LOCKED,
                actor_id=user.id,
                actor_email=user.email,
                resource_type="user",
                resource_id=user.id,
                ip_address=ctx.ip_address,
                user_agent=ctx.user_agent,
                success=False,
            )
            logger.warning("auth.account_locked", user_id=str(user.id))
        await self._record_failed_login(user.id, user.email, ctx, reason=reason)

    async def _record_failed_login(
        self,
        user_id: object,
        email: str,
        ctx: RequestContext,
        *,
        reason: str,
    ) -> None:
        await self.audit.record(
            AuditAction.USER_LOGIN_FAILED,
            actor_id=user_id,  # type: ignore[arg-type]
            actor_email=UserRepository.normalize_email(email),
            resource_type="user",
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            success=False,
            context={"reason": reason},
        )
