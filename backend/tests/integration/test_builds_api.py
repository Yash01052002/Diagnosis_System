"""Tests for firmware build upload and indexing."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    elf_fixture: Path,
    *,
    firmware_version: str = "1.4.2",
    build_version: str | None = "a1b2c3d",
    filename: str = "fw.elf",
) -> dict:
    data = {"firmware_version": firmware_version}
    if build_version is not None:
        data["build_version"] = build_version
    response = await client.post(
        "/api/v1/builds",
        data=data,
        files={"file": (filename, elf_fixture.read_bytes(), "application/octet-stream")},
        headers=headers,
    )
    return response


class TestUpload:
    async def test_engineer_uploads_and_indexes(
        self, client: AsyncClient, auth_headers, engineer_user, elf_fixture: Path
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await _upload(client, headers, elf_fixture)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "indexed"
        assert body["symbol_count"] > 0
        assert body["has_debug_info"] is True
        assert body["arch"]
        assert "symbols" in body["message"]

    async def test_viewer_cannot_upload(
        self, client: AsyncClient, auth_headers, viewer_user, elf_fixture: Path
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await _upload(client, headers, elf_fixture)

        assert response.status_code == 403

    async def test_viewer_can_list(
        self, client: AsyncClient, auth_headers, viewer_user, build_factory
    ) -> None:
        await build_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/builds", headers=headers)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_reupload_replaces(
        self, client: AsyncClient, auth_headers, engineer_user, elf_fixture: Path
    ) -> None:
        """Re-uploading the same (firmware, build, type) supersedes the old row."""
        headers = await auth_headers(engineer_user.email)

        first = await _upload(client, headers, elf_fixture)
        second = await _upload(client, headers, elf_fixture)

        assert first.json()["id"] == second.json()["id"], "same identity, same row"
        listing = await client.get("/api/v1/builds", headers=headers)
        assert listing.json()["total"] == 1

    async def test_empty_file_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/builds",
            data={"firmware_version": "1.0.0"},
            files={"file": ("empty.elf", b"", "application/octet-stream")},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_garbage_file_is_rejected(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)

        response = await client.post(
            "/api/v1/builds",
            data={"firmware_version": "1.0.0"},
            files={"file": ("fw.elf", b"not an elf at all", "application/octet-stream")},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_map_file_is_indexed(
        self, client: AsyncClient, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers(engineer_user.email)
        map_text = (
            " .text  0x08000000  0x40\n"
            "        0x0000000008000000  vTaskStartScheduler\n"
            "        0x0000000008001a2c  vTaskDelay\n"
        )

        response = await client.post(
            "/api/v1/builds",
            data={"firmware_version": "2.0.0"},
            files={"file": ("fw.map", map_text.encode(), "text/plain")},
            headers=headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["artifact_type"] == "map"
        assert body["symbol_count"] == 2
        assert body["has_debug_info"] is False


class TestBuildManagement:
    async def test_get_build(
        self, client: AsyncClient, auth_headers, viewer_user, build_factory
    ) -> None:
        build = await build_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/builds/{build.id}", headers=headers)

        assert response.status_code == 200
        assert response.json()["id"] == str(build.id)

    async def test_storage_path_is_not_exposed(
        self, client: AsyncClient, auth_headers, viewer_user, build_factory
    ) -> None:
        build = await build_factory()
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/builds/{build.id}", headers=headers)

        assert "storage_path" not in response.json()

    async def test_unknown_build_returns_404(
        self, client: AsyncClient, auth_headers, viewer_user, seeded_roles
    ) -> None:
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/builds/{uuid.uuid4()}", headers=headers)

        assert response.status_code == 404

    async def test_engineer_cannot_delete(
        self, client: AsyncClient, auth_headers, engineer_user, build_factory
    ) -> None:
        build = await build_factory()
        headers = await auth_headers(engineer_user.email)

        response = await client.delete(f"/api/v1/builds/{build.id}", headers=headers)

        assert response.status_code == 403

    async def test_admin_deletes_build_and_file(
        self, client: AsyncClient, auth_headers, admin_user, build_factory
    ) -> None:
        build = await build_factory()
        stored = Path(build.storage_path)
        assert stored.is_file()
        headers = await auth_headers(admin_user.email)

        response = await client.delete(f"/api/v1/builds/{build.id}", headers=headers)

        assert response.status_code == 204
        assert not stored.is_file(), "the artifact file is removed too"

    async def test_search_by_firmware_version(
        self, client: AsyncClient, auth_headers, viewer_user, build_factory
    ) -> None:
        await build_factory(firmware_version="1.0.0")
        await build_factory(firmware_version="2.0.0", build_version="other")
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/builds?firmware_version=2.0.0", headers=headers)

        assert response.json()["total"] == 1
