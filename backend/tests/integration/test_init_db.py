"""Tests for the database bootstrap (roles + first administrator)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.init_db import DEFAULT_ROLES, ensure_roles, ensure_superuser
from app.repositories.user import RoleRepository, UserRepository
from app.schemas.auth import LoginRequest

# No module-level asyncio mark: this module mixes sync and async tests, and
# pytest-asyncio's auto mode already picks up the coroutines.


class TestSeeding:
    async def test_roles_are_created_and_seeding_is_idempotent(
        self, db_session: AsyncSession
    ) -> None:
        created = await ensure_roles(db_session)
        again = await ensure_roles(db_session)

        assert {role.name for role in created} == set(DEFAULT_ROLES)
        assert again == [], "a second run must not duplicate roles"
        assert len(await RoleRepository(db_session).list_all()) == len(DEFAULT_ROLES)

    async def test_superuser_is_created_once(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        await ensure_roles(db_session)

        user = await ensure_superuser(db_session, settings)
        duplicate = await ensure_superuser(db_session, settings)

        assert user is not None
        assert user.is_admin and user.is_active
        assert duplicate is None, "an existing admin must not be recreated"

    async def test_seeded_admin_can_actually_log_in(
        self, db_session: AsyncSession, settings: Settings, client: AsyncClient
    ) -> None:
        """Guards against a bootstrap address the login schema would reject.

        ``EmailStr`` rejects reserved domains such as ``.local``, so an address
        that seeds fine could still be impossible to authenticate with.
        """
        await ensure_roles(db_session)
        await ensure_superuser(db_session, settings)

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": settings.FIRST_SUPERUSER_EMAIL,
                "password": settings.FIRST_SUPERUSER_PASSWORD,
            },
        )

        assert response.status_code == 200, response.text
        assert [role["name"] for role in response.json()["user"]["roles"]] == ["admin"]


class TestBootstrapConfiguration:
    def test_default_bootstrap_email_is_deliverable(self) -> None:
        default = Settings.model_fields["FIRST_SUPERUSER_EMAIL"].default

        assert LoginRequest(email=default, password="irrelevant").email == default

    @pytest.mark.parametrize("email", ["admin@blackbox.local", "admin@localhost", "not-an-email"])
    def test_unusable_bootstrap_email_is_rejected_at_startup(self, email: str) -> None:
        with pytest.raises(PydanticValidationError):
            Settings(FIRST_SUPERUSER_EMAIL=email)

    async def test_bootstrap_email_is_normalised(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        await ensure_roles(db_session)
        upper = settings.model_copy(
            update={"FIRST_SUPERUSER_EMAIL": settings.FIRST_SUPERUSER_EMAIL.upper()}
        )

        user = await ensure_superuser(db_session, upper)

        assert user is not None
        assert user.email == UserRepository.normalize_email(settings.FIRST_SUPERUSER_EMAIL)
