"""Integration tests for the knowledge-base (document ingestion + search) API."""

from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.asyncio

# A passage that overlaps strongly with a HardFault-in-SensorTask crash query,
# so hashing-embedding retrieval clears the relevance floor deterministically.
HARDFAULT_DOC = (
    "HardFault troubleshooting for FreeRTOS tasks on STM32.\n\n"
    "A HardFault raised inside a FreeRTOS task such as the SensorTask is most "
    "often caused by a task stack overflow. When a task overflows its stack the "
    "MPU or memory access traps as a HardFault escalated from a bus fault. "
    "Check the CFSR and BFAR fault registers, enable configCHECK_FOR_STACK_OVERFLOW, "
    "and increase the SensorTask stack depth. A HardFault in a FreeRTOS task "
    "usually points at stack corruption or an invalid pointer dereference."
)

SPI_DOC = (
    "SPI peripheral configuration on STM32. To configure the SPI baud rate set "
    "the prescaler bits in the CR1 control register. Select the clock polarity "
    "and phase, choose master or slave mode, and enable the peripheral. The DMA "
    "stream can be attached for high-throughput transfers."
)


async def _create_document(client, headers, *, title, content, source_type="troubleshooting"):
    return await client.post(
        "/api/v1/knowledge-base/documents",
        headers=headers,
        json={"title": title, "content": content, "source_type": source_type},
    )


class TestIngestion:
    async def test_engineer_can_ingest_and_it_indexes(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        response = await _create_document(
            client, headers, title="HardFault notes", content=HARDFAULT_DOC
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "indexed"
        assert body["chunk_count"] >= 1
        assert body["embedding_model"] == "hashing-384"

    async def test_viewer_cannot_ingest(self, client, auth_headers, viewer_user) -> None:
        headers = await auth_headers("viewer@example.com")
        response = await _create_document(
            client, headers, title="nope", content=HARDFAULT_DOC
        )
        assert response.status_code == 403

    async def test_duplicate_content_conflicts(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        first = await _create_document(
            client, headers, title="First", content=HARDFAULT_DOC
        )
        assert first.status_code == 201
        again = await _create_document(
            client, headers, title="Second copy", content=HARDFAULT_DOC
        )
        assert again.status_code == 409

    async def test_empty_content_is_rejected(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        response = await client.post(
            "/api/v1/knowledge-base/documents",
            headers=headers,
            json={"title": "blank", "content": "   \n\n  ", "source_type": "other"},
        )
        # Pydantic min_length=1 rejects before the service does; either way it is a 422.
        assert response.status_code == 422

    async def test_upload_text_file(self, client, auth_headers, engineer_user) -> None:
        headers = await auth_headers("engineer@example.com")
        files = {"file": ("hardfault.md", io.BytesIO(HARDFAULT_DOC.encode()), "text/markdown")}
        response = await client.post(
            "/api/v1/knowledge-base/documents/upload",
            headers=headers,
            files=files,
            data={"source_type": "troubleshooting"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "indexed"
        assert body["original_filename"] == "hardfault.md"

    async def test_upload_rejects_non_utf8(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        files = {"file": ("manual.pdf", io.BytesIO(b"\xff\xfe\x00binary"), "application/pdf")}
        response = await client.post(
            "/api/v1/knowledge-base/documents/upload",
            headers=headers,
            files=files,
        )
        assert response.status_code == 422


class TestListingAndStats:
    async def test_viewer_can_list_and_read_stats(
        self, client, auth_headers, engineer_user, viewer_user
    ) -> None:
        eng = await auth_headers("engineer@example.com")
        await _create_document(client, eng, title="HardFault notes", content=HARDFAULT_DOC)

        viewer = await auth_headers("viewer@example.com")
        listing = await client.get("/api/v1/knowledge-base/documents", headers=viewer)
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

        stats = await client.get("/api/v1/knowledge-base/stats", headers=viewer)
        assert stats.status_code == 200
        payload = stats.json()
        assert payload["documents"] == 1
        assert payload["chunks"] >= 1
        assert payload["embedding_provider"] == "hashing"
        assert payload["vector_store"] == "database"

    async def test_filter_by_source_type(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        await _create_document(
            client, headers, title="HF", content=HARDFAULT_DOC, source_type="troubleshooting"
        )
        await _create_document(
            client, headers, title="SPI", content=SPI_DOC, source_type="stm32_reference"
        )

        filtered = await client.get(
            "/api/v1/knowledge-base/documents?source_type=stm32_reference", headers=headers
        )
        assert filtered.status_code == 200
        items = filtered.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "SPI"


class TestSearch:
    async def test_engineer_search_finds_relevant_passage(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        await _create_document(client, headers, title="HardFault notes", content=HARDFAULT_DOC)
        await _create_document(
            client, headers, title="SPI config", content=SPI_DOC, source_type="stm32_reference"
        )

        response = await client.post(
            "/api/v1/knowledge-base/search",
            headers=headers,
            json={"query": "HardFault in FreeRTOS SensorTask stack overflow"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["empty"] is False
        assert body["results"], "expected at least one hit above the relevance floor"
        # The HardFault passage must rank above the unrelated SPI passage.
        assert body["results"][0]["document_title"] == "HardFault notes"

    async def test_search_returns_empty_for_unrelated_query(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        await _create_document(client, headers, title="HardFault notes", content=HARDFAULT_DOC)

        response = await client.post(
            "/api/v1/knowledge-base/search",
            headers=headers,
            json={"query": "quarterly sales revenue projection spreadsheet"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["empty"] is True
        assert body["results"] == []

    async def test_viewer_cannot_search(
        self, client, auth_headers, viewer_user
    ) -> None:
        headers = await auth_headers("viewer@example.com")
        response = await client.post(
            "/api/v1/knowledge-base/search",
            headers=headers,
            json={"query": "anything"},
        )
        assert response.status_code == 403


class TestDelete:
    async def test_admin_can_delete(
        self, client, auth_headers, engineer_user, admin_user
    ) -> None:
        eng = await auth_headers("engineer@example.com")
        created = await _create_document(
            client, eng, title="HardFault notes", content=HARDFAULT_DOC
        )
        document_id = created.json()["id"]

        admin = await auth_headers("admin@example.com")
        deleted = await client.delete(
            f"/api/v1/knowledge-base/documents/{document_id}", headers=admin
        )
        assert deleted.status_code == 204

        gone = await client.get(
            f"/api/v1/knowledge-base/documents/{document_id}", headers=admin
        )
        assert gone.status_code == 404

    async def test_engineer_cannot_delete(
        self, client, auth_headers, engineer_user
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        created = await _create_document(
            client, headers, title="HardFault notes", content=HARDFAULT_DOC
        )
        document_id = created.json()["id"]

        response = await client.delete(
            f"/api/v1/knowledge-base/documents/{document_id}", headers=headers
        )
        assert response.status_code == 403
