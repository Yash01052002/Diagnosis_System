"""Integration tests for the analytics/dashboard API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.crash import CrashSeverity, CrashStatus, FaultType

pytestmark = pytest.mark.asyncio


async def _seed(device_factory, crash_factory):
    device = await device_factory(firmware_version="1.4.2")
    now = datetime.now(UTC)
    # Three crashes over three days: two critical (one open), one low.
    await crash_factory(
        device, severity=CrashSeverity.CRITICAL, status=CrashStatus.NEW, occurred_at=now
    )
    await crash_factory(
        device,
        fault_type=FaultType.BUS_FAULT,
        severity=CrashSeverity.CRITICAL,
        status=CrashStatus.RESOLVED,
        occurred_at=now - timedelta(days=1),
    )
    await crash_factory(
        device,
        fault_type=FaultType.WATCHDOG_RESET,
        severity=CrashSeverity.LOW,
        status=CrashStatus.NEW,
        occurred_at=now - timedelta(days=2),
    )
    return device


class TestDashboard:
    async def test_summary(self, client, auth_headers, viewer_user, device_factory, crash_factory):
        await _seed(device_factory, crash_factory)
        headers = await auth_headers("viewer@example.com")
        res = await client.get("/api/v1/analytics/summary", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["crashes"]["total"] == 3
        assert body["crashes"]["critical_open"] == 1
        assert body["devices"]["total"] == 1
        # One device with an open critical crash -> 0% healthy.
        assert body["device_health_score"] == 0
        faults = {item["key"]: item["count"] for item in body["by_fault_type"]}
        assert faults["hard_fault"] == 1 and faults["bus_fault"] == 1

    async def test_requires_auth(self, client):
        assert (await client.get("/api/v1/analytics/summary")).status_code == 401


class TestDistributions:
    async def test_crash_trend_is_gap_filled(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ):
        await _seed(device_factory, crash_factory)
        headers = await auth_headers("viewer@example.com")
        res = await client.get("/api/v1/analytics/crash-trend?days=7", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["days"] == 7
        assert len(body["points"]) == 7  # every day present, even zero days
        assert body["total"] == 3
        assert sum(p["critical"] for p in body["points"]) == 2

    async def test_fault_distribution(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ):
        await _seed(device_factory, crash_factory)
        headers = await auth_headers("viewer@example.com")
        res = await client.get("/api/v1/analytics/fault-distribution", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3
        severities = {i["key"]: i["count"] for i in body["by_severity"]}
        assert severities["critical"] == 2 and severities["low"] == 1

    async def test_firmware_comparison(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ):
        await _seed(device_factory, crash_factory)
        headers = await auth_headers("viewer@example.com")
        res = await client.get("/api/v1/analytics/firmware-comparison", headers=headers)
        assert res.status_code == 200
        firmwares = res.json()["firmwares"]
        assert firmwares[0]["firmware_version"] == "1.4.2"
        assert firmwares[0]["crashes"] == 3
        assert firmwares[0]["devices"] == 1

    async def test_device_reliability_mtbf(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ):
        await _seed(device_factory, crash_factory)
        headers = await auth_headers("viewer@example.com")
        res = await client.get("/api/v1/analytics/device-reliability", headers=headers)
        assert res.status_code == 200
        body = res.json()
        # 3 crashes spanning 2 days -> 48h / 2 intervals = 24h MTBF.
        assert body["devices"][0]["crashes"] == 3
        assert body["devices"][0]["mtbf_hours"] == pytest.approx(24.0, abs=0.1)
        assert body["fleet_mtbf_hours"] == pytest.approx(24.0, abs=0.1)

    async def test_confidence_distribution_empty(
        self, client, auth_headers, viewer_user
    ):
        headers = await auth_headers("viewer@example.com")
        res = await client.get("/api/v1/analytics/confidence-distribution", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 0
        assert body["average_score"] is None
