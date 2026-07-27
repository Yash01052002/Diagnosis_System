"""Tests for crash ingestion, history and triage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditLog, CrashReport
from tests.conftest import crash_payload

pytestmark = pytest.mark.asyncio


class TestIngestionAuth:
    async def test_device_key_submits(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/crashes", json=crash_payload(), headers={"X-API-Key": api_key}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["fault_type"] == "hard_fault"
        assert body["severity"] == "critical"
        assert body["status"] == "new"

    async def test_engineer_can_submit_on_behalf(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/crashes",
            json=crash_payload(device_id=device.device_id),
            headers=headers,
        )

        assert response.status_code == 201, response.text

    async def test_viewer_cannot_submit(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.post(
            "/api/v1/crashes",
            json=crash_payload(device_id=device.device_id),
            headers=headers,
        )

        assert response.status_code == 403

    async def test_anonymous_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/crashes", json=crash_payload())

        assert response.status_code == 401

    async def test_revoked_key_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device, revoked=True)

        response = await client.post(
            "/api/v1/crashes", json=crash_payload(), headers={"X-API-Key": api_key}
        )

        assert response.status_code == 401

    async def test_key_identifies_the_device_regardless_of_body(
        self, client: AsyncClient, device_factory, api_key_factory, db_session: AsyncSession
    ) -> None:
        """A device cannot file a crash against someone else's hardware."""
        owner = await device_factory()
        victim = await device_factory()
        api_key = await api_key_factory(owner)

        response = await client.post(
            "/api/v1/crashes",
            json=crash_payload(device_id=victim.device_id),
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 201
        stored = (await db_session.execute(select(CrashReport))).scalars().one()
        assert stored.device_id == owner.id


class TestIngestionParsing:
    async def test_full_payload_is_stored(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        created = await client.post(
            "/api/v1/crashes",
            json=crash_payload(device_id=device.device_id),
            headers=headers,
        )
        detail = await client.get(f"/api/v1/crashes/{created.json()['id']}", headers=headers)

        body = detail.json()
        assert body["program_counter"] == 0x08001A2C
        assert body["link_register"] == 0x08001A0F
        assert body["register_dump"]["psr"] == 0x61000000
        assert body["stack_dump"]["words"] == [0x08001A2C, 0x20017FB0]
        assert body["task_name"] == "SensorTask"
        assert body["build_version"] == "a1b2c3d"
        assert body["device"]["device_id"] == device.device_id

    async def test_messy_payload_is_accepted_with_warnings(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/crashes",
            json={
                "firmware_version": "1.0.0",
                "fault_type": "???",
                "timestamp": "whenever",
                "pc": "nonsense",
            },
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["fault_type"] == "unknown"
        assert len(body["warnings"]) >= 3, "problems are reported, not hidden"

    async def test_camel_case_payload(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/crashes",
            json={
                "firmwareVersion": "2.0.0",
                "faultType": "busFault",
                "taskName": "CommsTask",
                "programCounter": "0x08001A2C",
            },
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 201
        assert response.json()["fault_type"] == "bus_fault"

    async def test_unknown_fields_are_preserved_in_raw_payload(
        self, client: AsyncClient, device_factory, api_key_factory, db_session: AsyncSession
    ) -> None:
        """A newer firmware adding a field must not lose it."""
        device = await device_factory()
        api_key = await api_key_factory(device)

        await client.post(
            "/api/v1/crashes",
            json=crash_payload(cpu_temperature_c=71.5, battery_mv=3712),
            headers={"X-API-Key": api_key},
        )

        stored = (await db_session.execute(select(CrashReport))).scalars().one()
        assert stored.raw_payload["cpu_temperature_c"] == 71.5
        assert stored.raw_payload["battery_mv"] == 3712

    async def test_missing_firmware_version_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/crashes",
            json={"fault_type": "HardFault"},
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 422

    async def test_report_without_any_fault_evidence_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/crashes",
            json={"firmware_version": "1.0.0"},
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 422

    async def test_far_future_timestamp_is_rejected(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)
        future = (datetime.now(UTC) + timedelta(days=400)).isoformat()

        response = await client.post(
            "/api/v1/crashes",
            json=crash_payload(timestamp=future),
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 422
        assert "clock" in response.json()["error"]["message"]

    async def test_unknown_device_returns_404(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/crashes",
            json=crash_payload(device_id="STM32-NEVER-REGISTERED"),
            headers=headers,
        )

        assert response.status_code == 404
        assert "Register the device" in response.json()["error"]["message"]

    async def test_missing_device_id_without_key_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post("/api/v1/crashes", json=crash_payload(), headers=headers)

        assert response.status_code == 422

    async def test_serial_number_resolves_the_device(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory
    ) -> None:
        device = await device_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/crashes",
            json=crash_payload(device_id=device.serial_number),
            headers=headers,
        )

        assert response.status_code == 201


class TestIngestionSideEffects:
    async def test_submission_marks_the_device_online(
        self, client: AsyncClient, device_factory, api_key_factory
    ) -> None:
        """A device that is crashing must not also be reported as offline."""
        device = await device_factory(last_online_at=None)
        api_key = await api_key_factory(device)

        await client.post("/api/v1/crashes", json=crash_payload(), headers={"X-API-Key": api_key})

        headers = {"X-API-Key": api_key}
        seen = await client.post("/api/v1/devices/heartbeat", headers=headers)
        assert seen.json()["last_online_at"] is not None

    async def test_duplicate_submission_is_collapsed(
        self, client: AsyncClient, device_factory, api_key_factory, db_session: AsyncSession
    ) -> None:
        """A retried upload must not double-count."""
        device = await device_factory()
        api_key = await api_key_factory(device)
        payload = crash_payload()

        first = await client.post("/api/v1/crashes", json=payload, headers={"X-API-Key": api_key})
        second = await client.post("/api/v1/crashes", json=payload, headers={"X-API-Key": api_key})

        assert first.json()["id"] == second.json()["id"]
        assert any("duplicate" in w for w in second.json()["warnings"])
        stored = (await db_session.execute(select(CrashReport))).scalars().all()
        assert len(stored) == 1

    async def test_different_crashes_are_not_collapsed(
        self, client: AsyncClient, device_factory, api_key_factory, db_session: AsyncSession
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        await client.post("/api/v1/crashes", json=crash_payload(), headers={"X-API-Key": api_key})
        await client.post(
            "/api/v1/crashes",
            json=crash_payload(pc="0x08009999"),
            headers={"X-API-Key": api_key},
        )

        stored = (await db_session.execute(select(CrashReport))).scalars().all()
        assert len(stored) == 2

    async def test_ingestion_is_audited(
        self, client: AsyncClient, device_factory, api_key_factory, db_session: AsyncSession
    ) -> None:
        device = await device_factory()
        api_key = await api_key_factory(device)

        await client.post("/api/v1/crashes", json=crash_payload(), headers={"X-API-Key": api_key})

        actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert AuditAction.CRASH_RECEIVED in actions

    async def test_rejected_report_is_audited(
        self, client: AsyncClient, device_factory, api_key_factory, db_session: AsyncSession
    ) -> None:
        """A build that starts sending garbage is itself a defect worth seeing."""
        device = await device_factory()
        api_key = await api_key_factory(device)
        future = (datetime.now(UTC) + timedelta(days=400)).isoformat()

        await client.post(
            "/api/v1/crashes",
            json=crash_payload(timestamp=future),
            headers={"X-API-Key": api_key},
        )

        actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert AuditAction.CRASH_REJECTED in actions


class TestCrashHistory:
    async def test_viewer_can_read(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        await crash_factory(device)
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/crashes", headers=headers)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_list_omits_heavy_dumps(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        await crash_factory(device)
        headers = await auth_headers(viewer_user.email)

        item = (await client.get("/api/v1/crashes", headers=headers)).json()["items"][0]

        assert "register_dump" not in item
        assert "stack_dump" not in item

    async def test_filters(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        first = await device_factory(firmware_version="1.0.0")
        second = await device_factory(firmware_version="2.0.0")
        await crash_factory(first, fault_type="hard_fault", severity="critical")
        await crash_factory(second, fault_type="bus_fault", severity="high")
        await crash_factory(second, fault_type="bus_fault", severity="high", status="resolved")
        headers = await auth_headers(viewer_user.email)

        async def total(query: str) -> int:
            response = await client.get(f"/api/v1/crashes?{query}", headers=headers)
            assert response.status_code == 200, response.text
            return int(response.json()["total"])

        assert await total(f"device_id={second.id}") == 2
        assert await total(f"device={first.device_id}") == 1
        assert await total("fault_type=bus_fault") == 2
        assert await total("severity=critical") == 1
        assert await total("status=resolved") == 1
        assert await total("firmware_version=2.0.0") == 2
        assert await total("task_name=SensorTask") == 3
        assert await total("diagnosed=false") == 3
        assert await total("diagnosed=true") == 0

    async def test_date_range_filter(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        now = datetime.now(UTC)
        await crash_factory(device, occurred_at=now)
        await crash_factory(device, occurred_at=now - timedelta(days=10))
        headers = await auth_headers(viewer_user.email)

        response = await client.get(
            "/api/v1/crashes",
            params={"occurred_from": (now - timedelta(days=1)).isoformat()},
            headers=headers,
        )

        assert response.json()["total"] == 1

    async def test_sorting(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        now = datetime.now(UTC)
        old = await crash_factory(device, occurred_at=now - timedelta(days=1))
        new = await crash_factory(device, occurred_at=now, program_counter=0x08009999)
        headers = await auth_headers(viewer_user.email)

        newest = await client.get("/api/v1/crashes?sort=-occurred_at", headers=headers)
        oldest = await client.get("/api/v1/crashes?sort=occurred_at", headers=headers)

        assert newest.json()["items"][0]["id"] == str(new.id)
        assert oldest.json()["items"][0]["id"] == str(old.id)

    async def test_unknown_sort_falls_back_safely(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        """An unknown sort key must not become an injection point."""
        device = await device_factory()
        await crash_factory(device)
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/crashes?sort=drop_table;--", headers=headers)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_detail_includes_dumps(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/crashes/{report.id}", headers=headers)

        assert response.status_code == 200
        assert "register_dump" in response.json()

    async def test_unknown_crash_returns_404(
        self, client: AsyncClient, auth_headers, viewer_user, seeded_roles
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/crashes/{uuid.uuid4()}", headers=headers)

        assert response.status_code == 404


class TestTriage:
    async def test_engineer_updates_triage_fields(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/crashes/{report.id}",
            json={"status": "investigating", "severity": "high", "notes": "Looking at DMA"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "investigating"
        assert body["severity"] == "high"
        assert body["notes"] == "Looking at DMA"

    async def test_fault_evidence_is_immutable(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        """Crash reports are forensic records; editing them destroys evidence."""
        device = await device_factory()
        report = await crash_factory(device, program_counter=0x08001A2C)
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/crashes/{report.id}",
            json={"status": "triaged", "program_counter": 0, "fault_type": "unknown"},
            headers=headers,
        )

        assert response.status_code == 200
        detail = await client.get(f"/api/v1/crashes/{report.id}", headers=headers)
        assert detail.json()["program_counter"] == 0x08001A2C
        assert detail.json()["fault_type"] == "hard_fault"

    async def test_viewer_cannot_triage(
        self, client: AsyncClient, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(viewer_user.email)

        response = await client.patch(
            f"/api/v1/crashes/{report.id}", json={"status": "resolved"}, headers=headers
        )

        assert response.status_code == 403

    async def test_empty_update_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(f"/api/v1/crashes/{report.id}", json={}, headers=headers)

        assert response.status_code == 422

    async def test_invalid_status_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/crashes/{report.id}", json={"status": "vibes"}, headers=headers
        )

        assert response.status_code == 422


class TestDeletion:
    async def test_engineer_cannot_delete(
        self, client: AsyncClient, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(engineer_user.email)

        response = await client.delete(f"/api/v1/crashes/{report.id}", headers=headers)

        assert response.status_code == 403

    async def test_admin_can_delete(
        self, client: AsyncClient, auth_headers, admin_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        report = await crash_factory(device)
        headers = await auth_headers(admin_user.email)

        response = await client.delete(f"/api/v1/crashes/{report.id}", headers=headers)

        assert response.status_code == 204
        assert (
            await client.get(f"/api/v1/crashes/{report.id}", headers=headers)
        ).status_code == 404

    async def test_deleting_a_device_removes_its_crashes(
        self, client: AsyncClient, auth_headers, admin_user, device_factory, crash_factory
    ) -> None:
        device = await device_factory()
        await crash_factory(device)
        headers = await auth_headers(admin_user.email)

        await client.delete(f"/api/v1/devices/{device.id}", headers=headers)

        listing = await client.get("/api/v1/crashes", headers=headers)
        assert listing.json()["total"] == 0
