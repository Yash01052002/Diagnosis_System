"""Integration tests for CSV / PDF export."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestCsvExport:
    async def test_crashes_csv(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ):
        device = await device_factory()
        await crash_factory(device, task_name="SensorTask")
        headers = await auth_headers("viewer@example.com")

        res = await client.get("/api/v1/export/crashes.csv", headers=headers)
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/csv")
        assert "attachment" in res.headers["content-disposition"]
        lines = res.text.strip().splitlines()
        assert lines[0].startswith("id,occurred_at,")
        assert len(lines) == 2  # header + one crash
        assert device.device_id in lines[1]

    async def test_requires_auth(self, client):
        assert (await client.get("/api/v1/export/crashes.csv")).status_code == 401


class TestPdfExport:
    async def test_analytics_pdf(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ):
        device = await device_factory()
        await crash_factory(device)
        headers = await auth_headers("viewer@example.com")

        res = await client.get("/api/v1/export/analytics.pdf", headers=headers)
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf"
        assert res.content[:5] == b"%PDF-"
        assert len(res.content) > 500
