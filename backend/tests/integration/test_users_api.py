"""Tests for user administration and role-based access control."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import DEFAULT_PASSWORD

pytestmark = pytest.mark.asyncio


class TestRBAC:
    async def test_viewer_cannot_list_users(
        self, client: AsyncClient, auth_headers, viewer_user
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/users", headers=headers)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "permission_denied"

    async def test_engineer_cannot_list_users(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.get("/api/v1/users", headers=headers)

        assert response.status_code == 403

    async def test_admin_can_list_users(
        self, client: AsyncClient, auth_headers, admin_user, viewer_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.get("/api/v1/users", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert {item["email"] for item in body["items"]} == {
            admin_user.email,
            viewer_user.email,
        }

    async def test_anonymous_is_unauthorized(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/users")

        assert response.status_code == 401


class TestUserSearch:
    async def test_filter_by_query_and_role(
        self, client: AsyncClient, auth_headers, admin_user, user_factory
    ) -> None:
        await user_factory(email="alice@example.com", roles=["engineer"], full_name="Alice")
        await user_factory(email="bob@example.com", roles=["viewer"], full_name="Bob")
        headers = await auth_headers(admin_user.email)

        by_name = await client.get("/api/v1/users?q=alice", headers=headers)
        by_role = await client.get("/api/v1/users?role=engineer", headers=headers)

        assert [item["email"] for item in by_name.json()["items"]] == ["alice@example.com"]
        assert [item["email"] for item in by_role.json()["items"]] == ["alice@example.com"]

    async def test_pagination_metadata(
        self, client: AsyncClient, auth_headers, admin_user, user_factory
    ) -> None:
        for index in range(4):
            await user_factory(email=f"user{index}@example.com")
        headers = await auth_headers(admin_user.email)

        response = await client.get("/api/v1/users?page=2&page_size=2", headers=headers)

        body = response.json()
        assert body["total"] == 5  # 4 created + the admin
        assert body["page"] == 2
        assert body["pages"] == 3
        assert len(body["items"]) == 2


class TestUserAdministration:
    async def test_admin_creates_user_with_roles(
        self, client: AsyncClient, auth_headers, admin_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.post(
            "/api/v1/users",
            json={
                "email": "engineer2@example.com",
                "password": DEFAULT_PASSWORD,
                "full_name": "Engineer Two",
                "roles": ["engineer"],
            },
            headers=headers,
        )

        assert response.status_code == 201, response.text
        assert [role["name"] for role in response.json()["roles"]] == ["engineer"]

    async def test_unknown_role_is_rejected(
        self, client: AsyncClient, auth_headers, admin_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.post(
            "/api/v1/users",
            json={
                "email": "ghost@example.com",
                "password": DEFAULT_PASSWORD,
                "roles": ["superhero"],
            },
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"]["roles"] == ["superhero"]

    async def test_role_promotion(
        self, client: AsyncClient, auth_headers, admin_user, viewer_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.patch(
            f"/api/v1/users/{viewer_user.id}",
            json={"roles": ["engineer"]},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert [role["name"] for role in response.json()["roles"]] == ["engineer"]

    async def test_deactivation_revokes_sessions(
        self, client: AsyncClient, auth_headers, admin_user, viewer_user, login
    ) -> None:
        victim_tokens = await login(viewer_user.email)
        headers = await auth_headers(admin_user.email)

        await client.patch(
            f"/api/v1/users/{viewer_user.id}", json={"is_active": False}, headers=headers
        )

        refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": victim_tokens["refresh_token"]}
        )
        assert refresh.status_code in (401, 403)

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {victim_tokens['access_token']}"},
        )
        assert me.status_code == 403, "existing access tokens must stop working"

    async def test_admin_cannot_demote_self(
        self, client: AsyncClient, auth_headers, admin_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.patch(
            f"/api/v1/users/{admin_user.id}", json={"roles": ["viewer"]}, headers=headers
        )

        assert response.status_code == 422

    async def test_admin_cannot_delete_self(
        self, client: AsyncClient, auth_headers, admin_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.delete(f"/api/v1/users/{admin_user.id}", headers=headers)

        assert response.status_code == 422

    async def test_delete_user(
        self, client: AsyncClient, auth_headers, admin_user, viewer_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.delete(f"/api/v1/users/{viewer_user.id}", headers=headers)

        assert response.status_code == 204
        assert (
            await client.get(f"/api/v1/users/{viewer_user.id}", headers=headers)
        ).status_code == 404

    async def test_unknown_user_returns_404(
        self, client: AsyncClient, auth_headers, admin_user
    ) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.get(f"/api/v1/users/{uuid.uuid4()}", headers=headers)

        assert response.status_code == 404


class TestSelfService:
    async def test_user_updates_own_profile(
        self, client: AsyncClient, auth_headers, viewer_user
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.patch(
            "/api/v1/users/me", json={"full_name": "Renamed"}, headers=headers
        )

        assert response.status_code == 200
        assert response.json()["full_name"] == "Renamed"

    async def test_self_update_cannot_change_roles(
        self, client: AsyncClient, auth_headers, viewer_user
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.patch(
            "/api/v1/users/me",
            json={"full_name": "Sneaky", "roles": ["admin"]},
            headers=headers,
        )

        assert response.status_code == 200
        assert [role["name"] for role in response.json()["roles"]] == ["viewer"], (
            "roles in a self-service payload must be ignored"
        )


class TestRolesEndpoint:
    async def test_admin_lists_roles(self, client: AsyncClient, auth_headers, admin_user) -> None:
        headers = await auth_headers(admin_user.email)

        response = await client.get("/api/v1/users/roles", headers=headers)

        assert response.status_code == 200
        assert {role["name"] for role in response.json()} == {
            "admin",
            "engineer",
            "viewer",
        }
