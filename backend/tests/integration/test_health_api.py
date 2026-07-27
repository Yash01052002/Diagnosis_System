"""Tests for health probes, error envelopes and OpenAPI generation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestHealth:
    async def test_liveness(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["environment"] == "test"

    async def test_readiness_reports_database(self, client: AsyncClient) -> None:
        response = await client.get("/health/ready")

        # Redis is not running in the test environment, so the overall status
        # may be degraded, but the database check must pass and the response
        # must not be a 503.
        assert response.status_code == 200
        assert response.json()["checks"]["database"] == "ok"


class TestErrorEnvelope:
    async def test_unknown_route_uses_envelope(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/does-not-exist")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    async def test_validation_errors_list_fields(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/auth/login", json={"email": "nope"})

        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert {item["field"] for item in fields} == {"email", "password"}


class TestMiddleware:
    async def test_request_id_is_echoed(self, client: AsyncClient) -> None:
        response = await client.get("/health", headers={"X-Request-ID": "abc-123"})

        assert response.headers["X-Request-ID"] == "abc-123"

    async def test_request_id_is_generated(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.headers.get("X-Request-ID")

    async def test_security_headers(self, client: AsyncClient) -> None:
        response = await client.get("/health")

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


class TestOpenAPI:
    async def test_schema_is_generated(self, client: AsyncClient) -> None:
        response = await client.get("/openapi.json")

        assert response.status_code == 200
        schema = response.json()
        assert "/api/v1/auth/login" in schema["paths"]
        assert "BearerAuth" in schema["components"]["securitySchemes"]

    async def test_docs_available_outside_production(self, client: AsyncClient) -> None:
        assert (await client.get("/docs")).status_code == 200
