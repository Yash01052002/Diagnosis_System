"""Integration tests for notifications and alert escalation."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _submit_crash(client, api_key, *, fault="HardFault"):
    return await client.post(
        "/api/v1/crashes",
        headers={"X-API-Key": api_key},
        json={
            "firmware_version": "1.4.2",
            "fault_type": fault,
            "task_name": "SensorTask",
            "pc": "0x08001A2C",
        },
    )


class TestCrashAlerts:
    async def test_critical_crash_notifies_staff(
        self, client, auth_headers, admin_user, engineer_user, viewer_user,
        device_factory, api_key_factory,
    ):
        device = await device_factory()
        key = await api_key_factory(device)

        res = await _submit_crash(client, key)
        assert res.status_code == 201, res.text

        # Admin and engineer are alerted; the viewer is not.
        admin_headers = await auth_headers("admin@example.com")
        admin_list = await client.get("/api/v1/notifications", headers=admin_headers)
        assert admin_list.status_code == 200
        items = admin_list.json()["items"]
        assert len(items) == 1
        assert items[0]["level"] == "critical"
        assert items[0]["category"] == "crash_alert"
        assert items[0]["resource_type"] == "crash_report"
        assert device.device_id in items[0]["title"]

        eng_headers = await auth_headers("engineer@example.com")
        eng_list = await client.get("/api/v1/notifications", headers=eng_headers)
        assert len(eng_list.json()["items"]) == 1

        viewer_headers = await auth_headers("viewer@example.com")
        viewer_list = await client.get("/api/v1/notifications", headers=viewer_headers)
        assert viewer_list.json()["items"] == []

    async def test_below_threshold_no_alert(
        self, client, auth_headers, admin_user, device_factory, api_key_factory
    ):
        device = await device_factory()
        key = await api_key_factory(device)
        # A usage fault derives "medium" severity, below the critical threshold.
        res = await _submit_crash(client, key, fault="UsageFault")
        assert res.status_code == 201

        admin_headers = await auth_headers("admin@example.com")
        admin_list = await client.get("/api/v1/notifications", headers=admin_headers)
        assert admin_list.json()["items"] == []


class TestInbox:
    async def test_unread_count_and_mark_read(
        self, client, auth_headers, admin_user, device_factory, api_key_factory
    ):
        device = await device_factory()
        key = await api_key_factory(device)
        await _submit_crash(client, key)
        headers = await auth_headers("admin@example.com")

        count = await client.get("/api/v1/notifications/unread-count", headers=headers)
        assert count.json()["count"] == 1

        listed = await client.get("/api/v1/notifications", headers=headers)
        note_id = listed.json()["items"][0]["id"]

        read = await client.post(f"/api/v1/notifications/{note_id}/read", headers=headers)
        assert read.status_code == 200
        assert read.json()["read_at"] is not None

        count2 = await client.get("/api/v1/notifications/unread-count", headers=headers)
        assert count2.json()["count"] == 0

    async def test_mark_all_read(
        self, client, auth_headers, admin_user, device_factory, api_key_factory
    ):
        device = await device_factory()
        key = await api_key_factory(device)
        await _submit_crash(client, key)
        await _submit_crash(client, key, fault="MemManageFault")
        headers = await auth_headers("admin@example.com")

        res = await client.post("/api/v1/notifications/read-all", headers=headers)
        assert res.status_code == 200
        count = await client.get("/api/v1/notifications/unread-count", headers=headers)
        assert count.json()["count"] == 0


class TestAlertSettings:
    async def test_admin_reads_and_updates(self, client, auth_headers, admin_user):
        headers = await auth_headers("admin@example.com")
        res = await client.get("/api/v1/notifications/settings", headers=headers)
        assert res.status_code == 200
        assert res.json()["min_severity"] == "critical"

        patched = await client.patch(
            "/api/v1/notifications/settings",
            headers=headers,
            json={"min_severity": "high", "email_enabled": True},
        )
        assert patched.status_code == 200
        assert patched.json()["min_severity"] == "high"
        assert patched.json()["email_enabled"] is True

        # Persisted.
        again = await client.get("/api/v1/notifications/settings", headers=headers)
        assert again.json()["min_severity"] == "high"

    async def test_non_admin_forbidden(self, client, auth_headers, viewer_user):
        headers = await auth_headers("viewer@example.com")
        assert (
            await client.get("/api/v1/notifications/settings", headers=headers)
        ).status_code == 403
