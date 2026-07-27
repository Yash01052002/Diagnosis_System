"""Idempotent database bootstrap: default roles and the first administrator.

Run via ``python -m app.db.init_db`` (the Docker entrypoint does this after
applying migrations).
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import SessionFactory, dispose_engine
from app.models.user import Role, RoleName, User
from app.repositories.user import RoleRepository, UserRepository

logger = get_logger(__name__)

DEFAULT_ROLES: dict[str, str] = {
    RoleName.ADMIN: "Full administrative access, including user and audit management",
    RoleName.ENGINEER: "Manage devices, crash reports and AI diagnoses",
    RoleName.VIEWER: "Read-only access to dashboards and crash history",
}


async def ensure_roles(session: AsyncSession) -> list[Role]:
    """Create any missing built-in role. Existing rows are left untouched."""
    repository = RoleRepository(session)
    created: list[Role] = []
    for name, description in DEFAULT_ROLES.items():
        if await repository.get_by_name(name) is None:
            created.append(await repository.create(name=name, description=description))
            logger.info("init_db.role_created", role=name)
    if created:
        await session.commit()
    return created


async def ensure_superuser(session: AsyncSession, settings: Settings) -> User | None:
    """Create the bootstrap administrator if it does not already exist."""
    users = UserRepository(session)
    roles = RoleRepository(session)
    email = UserRepository.normalize_email(settings.FIRST_SUPERUSER_EMAIL)

    if await users.email_exists(email):
        logger.info("init_db.superuser_exists", email=email)
        return None

    admin_role = await roles.get_by_name(RoleName.ADMIN)
    user = User(
        email=email,
        full_name="BlackBox Administrator",
        hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
        is_active=True,
        is_verified=True,
    )
    if admin_role is not None:
        user.roles.append(admin_role)
    users.add(user)
    await session.commit()

    logger.warning(
        "init_db.superuser_created",
        email=email,
        hint="Change FIRST_SUPERUSER_PASSWORD before deploying.",
    )
    return user


async def init_db() -> None:
    """Entry point used by the container start-up script."""
    settings = get_settings()
    configure_logging(settings)
    async with SessionFactory() as session:
        await ensure_roles(session)
        await ensure_superuser(session, settings)
    await dispose_engine()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(init_db())
