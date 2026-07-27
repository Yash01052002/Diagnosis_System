"""User administration service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.audit_log import AuditAction
from app.models.user import Role, User
from app.repositories.user import RefreshTokenRepository, RoleRepository, UserRepository
from app.schemas.user import UserAdminCreate, UserAdminUpdate, UserUpdate
from app.services.audit import AuditService
from app.services.auth import RequestContext


class UserService:
    """CRUD and role management for user accounts."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        users: UserRepository,
        roles: RoleRepository,
        refresh_tokens: RefreshTokenRepository,
        audit: AuditService,
    ) -> None:
        self.session = session
        self.users = users
        self.roles = roles
        self.refresh_tokens = refresh_tokens
        self.audit = audit

    # -- reads ---------------------------------------------------------
    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.users.get_with_roles(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    async def search(
        self,
        *,
        query: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[User], int]:
        return await self.users.search(
            query=query, role=role, is_active=is_active, offset=offset, limit=limit
        )

    async def list_roles(self) -> list[Role]:
        return await self.roles.list_all()

    # -- writes --------------------------------------------------------
    async def create(
        self, payload: UserAdminCreate, *, actor: User, ctx: RequestContext | None = None
    ) -> User:
        ctx = ctx or RequestContext()
        email = UserRepository.normalize_email(payload.email)
        if await self.users.email_exists(email):
            raise ConflictError("An account with this email already exists.")

        user = User(
            email=email,
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            is_active=payload.is_active,
            is_verified=payload.is_verified,
        )
        user.roles = await self._resolve_roles(payload.roles)
        self.users.add(user)
        await self.session.flush()

        await self.audit.record(
            AuditAction.USER_UPDATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"operation": "create", "roles": payload.roles},
        )
        await self.session.commit()
        await self.session.refresh(user, attribute_names=["roles"])
        return user

    async def update(
        self,
        user_id: uuid.UUID,
        payload: UserUpdate | UserAdminUpdate,
        *,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> User:
        """Apply a partial update. Only fields present in the payload change."""
        ctx = ctx or RequestContext()
        user = await self.get(user_id)
        data = payload.model_dump(exclude_unset=True)
        changed: dict[str, object] = {}

        if "email" in data and data["email"]:
            new_email = UserRepository.normalize_email(str(data["email"]))
            if new_email != user.email and await self.users.email_exists(new_email):
                raise ConflictError("An account with this email already exists.")
            user.email = new_email
            changed["email"] = new_email

        if "full_name" in data:
            user.full_name = data["full_name"]
            changed["full_name"] = data["full_name"]

        if isinstance(payload, UserAdminUpdate):
            if "is_active" in data and data["is_active"] is not None:
                is_active = bool(data["is_active"])
                # Deactivating must also terminate live sessions.
                if not is_active and user.is_active:
                    await self.refresh_tokens.revoke_all_for_user(user.id)
                user.is_active = is_active
                changed["is_active"] = is_active

            if "is_verified" in data and data["is_verified"] is not None:
                user.is_verified = bool(data["is_verified"])
                changed["is_verified"] = user.is_verified

            if "roles" in data and data["roles"] is not None:
                roles = [str(role) for role in data["roles"]]
                self._guard_last_admin(user, actor, new_roles=roles)
                user.roles = await self._resolve_roles(roles)
                changed["roles"] = roles

        await self.session.flush()
        await self.audit.record(
            AuditAction.USER_ROLES_CHANGED if "roles" in changed else AuditAction.USER_UPDATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"changed": list(changed.keys()), **changed},
        )
        await self.session.commit()
        await self.session.refresh(user, attribute_names=["roles"])
        return user

    async def delete(
        self, user_id: uuid.UUID, *, actor: User, ctx: RequestContext | None = None
    ) -> None:
        ctx = ctx or RequestContext()
        user = await self.get(user_id)
        if user.id == actor.id:
            raise ValidationError("You cannot delete your own account.")

        await self.audit.record(
            AuditAction.USER_DELETED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="user",
            resource_id=user.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"email": user.email},
        )
        await self.users.delete(user)
        await self.session.commit()

    # -- internals -----------------------------------------------------
    async def _resolve_roles(self, names: Sequence[str]) -> list[Role]:
        """Map role names to rows, rejecting unknown names."""
        wanted = sorted({name.strip().lower() for name in names if name.strip()})
        if not wanted:
            raise ValidationError("At least one role must be assigned.")
        roles = await self.roles.get_by_names(wanted)
        found = {role.name for role in roles}
        missing = [name for name in wanted if name not in found]
        if missing:
            raise ValidationError(
                "Unknown role(s): " + ", ".join(missing), details={"roles": missing}
            )
        return roles

    @staticmethod
    def _guard_last_admin(user: User, actor: User, *, new_roles: Sequence[str]) -> None:
        """Prevent an admin from removing their own admin role by accident."""
        if user.id == actor.id and user.is_admin and "admin" not in new_roles:
            raise ValidationError("You cannot remove your own admin role.")
