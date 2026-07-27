"""Tests for the device fleet endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def device_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "device_id": "STM32-F4-9001",
        "serial_number": "SN-2026-999001",
        "firmware_version": "1.4.2",
        "hardware_model": "STM32F407VG",
        "location": "Lab A",
        "tags": ["field-trial"],
    }
    payload.update(overrides)
    return payload


class TestDeviceRBAC:
    async def test_viewer_can_list(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        await device_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/devices", headers=headers)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_viewer_cannot_create(
        self, client: AsyncClient, auth_headers, viewer_user
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.post("/api/v1/devices", json=device_payload(), headers=headers)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "permission_denied"

    async def test_engineer_can_create(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.post("/api/v1/devices", json=device_payload(), headers=headers)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["device_id"] == "STM32-F4-9001"
        assert body["tags"] == ["field-trial"]
        assert body["owner"]["email"] == engineer_user.email, "creator becomes the owner"

    async def test_engineer_cannot_delete(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.delete(f"/api/v1/devices/{device.id}", headers=headers)

        assert response.status_code == 403, "deleting cascades to crash history"

    async def test_admin_can_delete(
        self, client: AsyncClient, auth_headers, admin_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        await crash_factory(device)
        headers = await auth_headers(admin_user.email)

        response = await client.delete(f"/api/v1/devices/{device.id}", headers=headers)

        assert response.status_code == 204
        assert (
            await client.get(f"/api/v1/devices/{device.id}", headers=headers)
        ).status_code == 404

    async def test_anonymous_is_rejected(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/devices")).status_code == 401


class TestDeviceCreation:
    async def test_duplicate_device_id_conflicts(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        existing = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/devices",
            json=device_payload(device_id=existing.device_id, serial_number="SN-OTHER"),
            headers=headers,
        )

        assert response.status_code == 409

    async def test_duplicate_serial_conflicts(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        existing = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/devices",
            json=device_payload(device_id="STM32-OTHER", serial_number=existing.serial_number),
            headers=headers,
        )

        assert response.status_code == 409

    @pytest.mark.parametrize("bad_id", ["has spaces", "semi;colon", "a", "-leading"])
    async def test_invalid_identifier_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user, bad_id: str
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/devices", json=device_payload(device_id=bad_id), headers=headers
        )

        assert response.status_code == 422

    async def test_tags_are_normalised_and_deduplicated(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/devices",
            json=device_payload(tags=["Field-Trial", " EU-WEST ", "field-trial"]),
            headers=headers,
        )

        assert response.json()["tags"] == ["field-trial", "eu-west"]

    async def test_tags_are_shared_between_devices(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        """Two devices with the same label point at one tag row."""
        await device_factory(tags=["shared"])
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/devices", json=device_payload(tags=["shared"]), headers=headers
        )

        assert response.status_code == 201
        listing = await client.get("/api/v1/devices?tag=shared", headers=headers)
        assert listing.json()["total"] == 2


class TestDeviceSearch:
    async def test_filter_by_status_and_model(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        await device_factory(hardware_model="STM32F407VG")
        await device_factory(hardware_model="STM32H743", status="maintenance")
        headers = await auth_headers(viewer_user.email)

        by_model = await client.get("/api/v1/devices?hardware_model=STM32H743", headers=headers)
        by_status = await client.get("/api/v1/devices?status=maintenance", headers=headers)

        assert by_model.json()["total"] == 1
        assert by_status.json()["total"] == 1

    async def test_free_text_search(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        await device_factory(location="Reykjavik lab")
        await device_factory(location="Berlin lab")
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/devices?q=reykjavik", headers=headers)

        assert response.json()["total"] == 1

    async def test_filter_by_online_since(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        now = datetime.now(UTC)
        await device_factory(last_online_at=now)
        await device_factory(last_online_at=now - timedelta(days=7))
        headers = await auth_headers(viewer_user.email)

        # Passed via ``params`` so the "+00:00" offset is percent-encoded; a
        # raw "+" in a query string decodes as a space.
        response = await client.get(
            "/api/v1/devices",
            params={"online_since": (now - timedelta(days=1)).isoformat()},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1

    async def test_pagination(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        for _ in range(5):
            await device_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/devices?page=2&page_size=2", headers=headers)

        body = response.json()
        assert body["total"] == 5
        assert body["pages"] == 3
        assert len(body["items"]) == 2


class TestDeviceUpdate:
    async def test_update_fields_and_tags(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory(tags=["old"])
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/devices/{device.id}",
            json={"firmware_version": "2.0.0", "tags": ["new", "fleet-b"]},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["firmware_version"] == "2.0.0"
        assert body["tags"] == ["new", "fleet-b"]

    async def test_identifiers_are_immutable(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        """Crash history references these, so a change would rewrite the past."""
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/devices/{device.id}",
            json={"device_id": "STM32-RENAMED", "serial_number": "SN-RENAMED"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["device_id"] == device.device_id
        assert response.json()["serial_number"] == device.serial_number

    async def test_unknown_device_returns_404(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/devices/{uuid.uuid4()}", json={"location": "x"}, headers=headers
        )

        assert response.status_code == 404


class TestDeviceStats:
    async def test_counters(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        await crash_factory(device, status="new")
        await crash_factory(device, status="resolved")
        await crash_factory(device, status="new", occurred_at=datetime.now(UTC) - timedelta(days=5))
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/devices/{device.id}/stats", headers=headers)

        body = response.json()
        assert body["total_crashes"] == 3
        assert body["open_crashes"] == 2
        assert body["crashes_last_24h"] == 2


class TestApiKeys:
    async def test_create_returns_plaintext_once(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            f"/api/v1/devices/{device.id}/api-keys",
            json={"name": "fleet-key"},
            headers=headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["api_key"].startswith("bbx_")
        assert body["prefix"] in body["api_key"]

        listing = await client.get(f"/api/v1/devices/{device.id}/api-keys", headers=headers)
        assert "api_key" not in listing.json()[0], "the secret is never listed again"

    async def test_viewer_cannot_mint_keys(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.post(
            f"/api/v1/devices/{device.id}/api-keys", json={"name": "x"}, headers=headers
        )

        assert response.status_code == 403

    async def test_past_expiry_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        response = await client.post(
            f"/api/v1/devices/{device.id}/api-keys",
            json={"name": "expired", "expires_at": past},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_revocation(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)
        created = await client.post(
            f"/api/v1/devices/{device.id}/api-keys",
            json={"name": "temp"},
            headers=headers,
        )
        key_id = created.json()["id"]

        response = await client.delete(
            f"/api/v1/devices/{device.id}/api-keys/{key_id}", headers=headers
        )

        assert response.status_code == 204
        listing = await client.get(f"/api/v1/devices/{device.id}/api-keys", headers=headers)
        assert listing.json()[0]["revoked_at"] is not None

    async def test_key_of_another_device_is_not_revocable(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        first = await device_factory()
        second = await device_factory()
        headers = await auth_headers(engineer_user.email)
        created = await client.post(
            f"/api/v1/devices/{first.id}/api-keys", json={"name": "k"}, headers=headers
        )

        response = await client.delete(
            f"/api/v1/devices/{second.id}/api-keys/{created.json()['id']}",
            headers=headers,
        )

        assert response.status_code == 404


class TestHeartbeat:
    async def test_device_checks_in_with_its_key(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory(status="inactive")
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/devices/heartbeat",
            json={"firmware_version": "2.1.0"},
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["last_online_at"] is not None
        assert body["firmware_version"] == "2.1.0"
        assert body["status"] == "active", "a device that checked in is not inactive"

    async def test_maintenance_status_is_preserved(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        """An operator's decision outranks the device's own opinion."""
        device = await device_factory(status="maintenance")
        api_key = await api_key_factory(device)

        response = await client.post("/api/v1/devices/heartbeat", headers={"X-API-Key": api_key})

        assert response.json()["status"] == "maintenance"

    @pytest.mark.parametrize("header", [{}, {"X-API-Key": "garbage"}, {"X-API-Key": "bbx_a_b"}])
    async def test_bad_credentials_are_rejected(
        self, client: AsyncClient, header: dict[str, str]
    ) -> None:
        response = await client.post("/api/v1/devices/heartbeat", headers=header)

        assert response.status_code == 401

    async def test_revoked_key_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device, revoked=True)

        response = await client.post("/api/v1/devices/heartbeat", headers={"X-API-Key": api_key})

        assert response.status_code == 401

    async def test_expired_key_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device, expires_at=datetime.now(UTC) - timedelta(minutes=1))

        response = await client.post("/api/v1/devices/heartbeat", headers={"X-API-Key": api_key})

        assert response.status_code == 401

    async def test_decommissioned_device_key_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory(status="decommissioned")
        api_key = await api_key_factory(device)

        response = await client.post("/api/v1/devices/heartbeat", headers={"X-API-Key": api_key})

        assert response.status_code == 401

    async def test_key_is_scoped_to_its_own_device(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        first = await device_factory()
        await device_factory()
        api_key = await api_key_factory(first)

        response = await client.post("/api/v1/devices/heartbeat", headers={"X-API-Key": api_key})

        assert response.json()["id"] == str(first.id)
