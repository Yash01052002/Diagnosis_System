"""End-to-end tests for the authentication endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditLog, RefreshToken
from tests.conftest import DEFAULT_PASSWORD

pytestmark = pytest.mark.asyncio


class TestRegistration:
    async def test_register_creates_viewer(self, client: AsyncClient, seeded_roles: dict) -> None:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "New.User@Example.com",
                "password": DEFAULT_PASSWORD,
                "full_name": "New User",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["email"] == "new.user@example.com", "emails are normalised"
        assert [role["name"] for role in body["roles"]] == ["viewer"]
        assert "password" not in body and "hashed_password" not in body

    async def test_duplicate_email_conflicts(self, client: AsyncClient, viewer_user) -> None:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": viewer_user.email.upper(), "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"

    async def test_weak_password_is_rejected(self, client: AsyncClient, seeded_roles: dict) -> None:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "password"},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestLogin:
    async def test_successful_login_returns_tokens(self, client: AsyncClient, viewer_user) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"] and body["refresh_token"]
        assert body["user"]["email"] == viewer_user.email

    async def test_email_is_case_insensitive(self, client: AsyncClient, viewer_user) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email.upper(), "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 200

    async def test_wrong_password_rejected(self, client: AsyncClient, viewer_user) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": "Wr0ng!Passw0rd"},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    async def test_unknown_email_gives_same_error(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials", (
            "unknown emails must be indistinguishable from wrong passwords"
        )

    async def test_inactive_account_rejected(self, client: AsyncClient, user_factory) -> None:
        user = await user_factory(email="inactive@example.com", is_active=False)

        response = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "inactive_user"

    async def test_account_locks_after_threshold(
        self, client: AsyncClient, viewer_user, settings
    ) -> None:
        for _ in range(settings.MAX_FAILED_LOGIN_ATTEMPTS):
            await client.post(
                "/api/v1/auth/login",
                json={"email": viewer_user.email, "password": "Wr0ng!Passw0rd"},
            )

        # Even the correct password is refused while the lockout is active.
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": DEFAULT_PASSWORD},
        )

        assert response.status_code == 423
        assert response.json()["error"]["code"] == "account_locked"


class TestTokenRefresh:
    async def test_refresh_rotates_token(self, client: AsyncClient, login, viewer_user) -> None:
        tokens = await login(viewer_user.email)

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )

        assert response.status_code == 200, response.text
        assert response.json()["refresh_token"] != tokens["refresh_token"]

    async def test_reused_refresh_token_is_rejected(
        self, client: AsyncClient, login, viewer_user
    ) -> None:
        tokens = await login(viewer_user.email)
        await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )

        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "invalid_token"

    async def test_access_token_cannot_be_used_as_refresh(
        self, client: AsyncClient, login, viewer_user
    ) -> None:
        tokens = await login(viewer_user.email)

        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
        )

        assert response.status_code == 401


class TestCurrentUser:
    async def test_me_requires_a_token(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401

    async def test_me_returns_profile(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.get("/api/v1/auth/me", headers=headers)

        assert response.status_code == 200
        assert response.json()["email"] == engineer_user.email

    async def test_garbage_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
        )

        assert response.status_code == 401


class TestLogout:
    async def test_logout_revokes_session(self, client: AsyncClient, login, viewer_user) -> None:
        tokens = await login(viewer_user.email)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers=headers,
        )

        assert response.status_code == 200
        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert replay.status_code == 401

    async def test_logout_all_sessions(
        self, client: AsyncClient, login, viewer_user, db_session: AsyncSession
    ) -> None:
        first = await login(viewer_user.email)
        second = await login(viewer_user.email)
        headers = {"Authorization": f"Bearer {second['access_token']}"}

        response = await client.post(
            "/api/v1/auth/logout", json={"all_sessions": True}, headers=headers
        )

        assert response.status_code == 200
        for tokens in (first, second):
            replay = await client.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert replay.status_code == 401

        stored = (await db_session.execute(select(RefreshToken))).scalars().all()
        assert stored and all(token.revoked_at is not None for token in stored)


class TestPasswordReset:
    async def test_full_reset_flow(self, client: AsyncClient, viewer_user, email_sender) -> None:
        forgot = await client.post(
            "/api/v1/auth/forgot-password", json={"email": viewer_user.email}
        )
        assert forgot.status_code == 200
        assert len(email_sender.outbox) == 1

        token = email_sender.outbox[0].text_body.split("token=")[1].split()[0]
        new_password = "N3w!Passw0rd"

        reset = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": new_password},
        )
        assert reset.status_code == 200, reset.text

        old = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": DEFAULT_PASSWORD},
        )
        assert old.status_code == 401

        new = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": new_password},
        )
        assert new.status_code == 200

    async def test_token_is_single_use(
        self, client: AsyncClient, viewer_user, email_sender
    ) -> None:
        await client.post("/api/v1/auth/forgot-password", json={"email": viewer_user.email})
        token = email_sender.outbox[0].text_body.split("token=")[1].split()[0]

        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "N3w!Passw0rd"},
        )
        replay = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "An0ther!Passw0rd"},
        )

        assert replay.status_code == 401

    async def test_unknown_email_does_not_leak(
        self, client: AsyncClient, seeded_roles, email_sender
    ) -> None:
        response = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
        )

        assert response.status_code == 200, "response must not reveal account existence"
        assert email_sender.outbox == []

    async def test_reset_revokes_existing_sessions(
        self, client: AsyncClient, login, viewer_user, email_sender
    ) -> None:
        tokens = await login(viewer_user.email)
        await client.post("/api/v1/auth/forgot-password", json={"email": viewer_user.email})
        token = email_sender.outbox[0].text_body.split("token=")[1].split()[0]

        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "N3w!Passw0rd"},
        )

        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert replay.status_code == 401

    async def test_invalid_token_rejected(self, client: AsyncClient, seeded_roles) -> None:
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "x" * 43, "new_password": "N3w!Passw0rd"},
        )

        assert response.status_code == 401


class TestChangePassword:
    async def test_change_password(self, client: AsyncClient, auth_headers, viewer_user) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": DEFAULT_PASSWORD, "new_password": "N3w!Passw0rd"},
            headers=headers,
        )

        assert response.status_code == 200
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": "N3w!Passw0rd"},
        )
        assert login.status_code == 200

    async def test_wrong_current_password_rejected(
        self, client: AsyncClient, auth_headers, viewer_user
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "Wr0ng!Passw0rd", "new_password": "N3w!Passw0rd"},
            headers=headers,
        )

        assert response.status_code == 401


class TestAuditTrail:
    async def test_login_events_are_recorded(
        self, client: AsyncClient, viewer_user, db_session: AsyncSession
    ) -> None:
        await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": "Wr0ng!Passw0rd"},
        )
        await client.post(
            "/api/v1/auth/login",
            json={"email": viewer_user.email, "password": DEFAULT_PASSWORD},
        )

        actions = (await db_session.execute(select(AuditLog.action, AuditLog.success))).all()
        recorded = {action for action, _ in actions}

        assert AuditAction.USER_LOGIN_FAILED in recorded
        assert AuditAction.USER_LOGIN in recorded
