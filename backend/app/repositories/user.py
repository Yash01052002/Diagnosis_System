"""Repositories for users, roles and authentication tokens."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.user import PasswordResetToken, RefreshToken, Role, User
from app.repositories.base import BaseRepository, affected_rows


class UserRepository(BaseRepository[User]):
    model = User

    @staticmethod
    def normalize_email(email: str) -> str:
        """Emails are matched case-insensitively and stored lower-cased."""
        return email.strip().lower()

    async def get_by_email(self, email: str) -> User | None:
        stmt = (
            select(User)
            .where(func.lower(User.email) == self.normalize_email(email))
            .options(selectinload(User.roles))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_with_roles(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id).options(selectinload(User.roles))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def email_exists(self, email: str) -> bool:
        stmt = (
            select(func.count())
            .select_from(User)
            .where(func.lower(User.email) == self.normalize_email(email))
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one()) > 0

    async def search(
        self,
        *,
        query: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[User], int]:
        """Filtered, paginated user listing. Returns ``(items, total)``."""
        stmt = select(User).options(selectinload(User.roles))
        count_stmt = select(func.count(func.distinct(User.id))).select_from(User)

        if query:
            pattern = f"%{query.strip().lower()}%"
            condition = or_(
                func.lower(User.email).like(pattern),
                func.lower(func.coalesce(User.full_name, "")).like(pattern),
            )
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
            count_stmt = count_stmt.where(User.is_active.is_(is_active))

        if role:
            stmt = stmt.join(User.roles).where(Role.name == role)
            count_stmt = count_stmt.join(User.roles).where(Role.name == role)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().unique().all()
        return items, total


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_names(self, names: Sequence[str]) -> list[Role]:
        if not names:
            return []
        stmt = select(Role).where(Role.name.in_(list(names)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[Role]:
        stmt = select(Role).order_by(Role.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_jti(self, jti: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.jti == jti).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active_by_jti(self, jti: str) -> RefreshToken | None:
        """Return the token only if it is neither revoked nor expired."""
        now = datetime.now(UTC)
        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.jti == jti,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def revoke(self, token: RefreshToken) -> None:
        if token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
            await self.session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Revoke every active session for a user (logout-everywhere)."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        result = await self.session.execute(stmt)
        return affected_rows(result)

    async def purge_expired(self, *, before: datetime | None = None) -> int:
        """Delete tokens that expired before ``before`` (housekeeping job)."""
        cutoff = before or datetime.now(UTC)
        from sqlalchemy import delete as sql_delete

        stmt = sql_delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        result = await self.session.execute(stmt)
        return affected_rows(result)


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    model = PasswordResetToken

    async def get_active_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        now = datetime.now(UTC)
        stmt = (
            select(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def invalidate_for_user(self, user_id: uuid.UUID) -> int:
        """Mark all outstanding reset tokens for a user as used."""
        stmt = (
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
        result = await self.session.execute(stmt)
        return affected_rows(result)
