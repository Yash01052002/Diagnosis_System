"""Integration tests for the RAG crash-diagnosis API.

These exercise the anti-hallucination contract end to end: a grounded crash
(one the knowledge base can explain) comes back with sources and a non-uncertain
label, while an ungrounded crash comes back explicitly ``uncertain`` with zero
sources — no invented answer.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

HARDFAULT_DOC = (
    "HardFault troubleshooting for FreeRTOS tasks on STM32.\n\n"
    "A HardFault raised inside a FreeRTOS task such as the SensorTask is most "
    "often caused by a task stack overflow. When a task overflows its stack the "
    "MPU or memory access traps as a HardFault escalated from a bus fault. "
    "Check the CFSR and BFAR fault registers, enable configCHECK_FOR_STACK_OVERFLOW, "
    "and increase the SensorTask stack depth. A HardFault in a FreeRTOS task "
    "usually points at stack corruption or an invalid pointer dereference."
)


async def _ingest(client, headers, *, title, content, source_type="troubleshooting"):
    response = await client.post(
        "/api/v1/knowledge-base/documents",
        headers=headers,
        json={"title": title, "content": content, "source_type": source_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestDiagnoseGrounded:
    async def test_grounded_crash_cites_sources(
        self, client, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        await _ingest(client, headers, title="HardFault notes", content=HARDFAULT_DOC)

        device = await device_factory()
        crash = await crash_factory(device, task_name="SensorTask")

        response = await client.post(
            f"/api/v1/crashes/{crash.id}/diagnose", headers=headers
        )
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["is_uncertain"] is False
        assert body["confidence_label"] in ("likely", "certain")
        assert body["sources"], "a grounded diagnosis must list its sources"
        assert body["sources"][0]["document_title"] == "HardFault notes"
        assert body["top_relevance"] is not None and body["top_relevance"] >= 0.18
        assert body["provider"] == "template"
        # The grounded template answer echoes the crash facts.
        assert "SensorTask" in body["root_cause"] or "stack" in body["root_cause"].lower()


class TestDiagnoseUngrounded:
    async def test_no_knowledge_base_is_explicitly_uncertain(
        self, client, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        device = await device_factory()
        crash = await crash_factory(device, task_name="SensorTask")

        response = await client.post(
            f"/api/v1/crashes/{crash.id}/diagnose", headers=headers
        )
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["is_uncertain"] is True
        assert body["confidence_label"] == "uncertain"
        assert body["sources"] == []
        assert body["confidence_score"] <= 0.2
        assert "cannot be determined" in body["root_cause"].lower()
        assert body["warnings"], "an ungrounded diagnosis must warn about weak grounding"

    async def test_only_irrelevant_docs_is_uncertain(
        self, client, auth_headers, engineer_user, device_factory, crash_factory
    ) -> None:
        headers = await auth_headers("engineer@example.com")
        await _ingest(
            client,
            headers,
            title="Payroll policy",
            content=(
                "The quarterly payroll reconciliation process reviews employee "
                "compensation, tax withholding schedules, and benefit deductions "
                "across all departments before the finance committee sign-off."
            ),
            source_type="other",
        )
        device = await device_factory()
        crash = await crash_factory(device, task_name="SensorTask")

        response = await client.post(
            f"/api/v1/crashes/{crash.id}/diagnose", headers=headers
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["is_uncertain"] is True
        assert body["sources"] == []


class TestDiagnosisRbacAndHistory:
    async def test_viewer_cannot_diagnose(
        self, client, auth_headers, viewer_user, device_factory, crash_factory
    ) -> None:
        headers = await auth_headers("viewer@example.com")
        device = await device_factory()
        crash = await crash_factory(device)
        response = await client.post(
            f"/api/v1/crashes/{crash.id}/diagnose", headers=headers
        )
        assert response.status_code == 403

    async def test_diagnose_unknown_crash_is_404(
        self, client, auth_headers, engineer_user
    ) -> None:
        import uuid

        headers = await auth_headers("engineer@example.com")
        response = await client.post(
            f"/api/v1/crashes/{uuid.uuid4()}/diagnose", headers=headers
        )
        assert response.status_code == 404

    async def test_history_accumulates_and_is_viewable(
        self, client, auth_headers, engineer_user, viewer_user, device_factory, crash_factory
    ) -> None:
        eng = await auth_headers("engineer@example.com")
        await _ingest(client, eng, title="HardFault notes", content=HARDFAULT_DOC)

        device = await device_factory()
        crash = await crash_factory(device, task_name="SensorTask")

        first = await client.post(f"/api/v1/crashes/{crash.id}/diagnose", headers=eng)
        second = await client.post(f"/api/v1/crashes/{crash.id}/diagnose", headers=eng)
        assert first.status_code == second.status_code == 201
        # Re-running keeps history rather than replacing.
        assert first.json()["id"] != second.json()["id"]

        viewer = await auth_headers("viewer@example.com")
        history = await client.get(
            f"/api/v1/crashes/{crash.id}/diagnoses", headers=viewer
        )
        assert history.status_code == 200
        items = history.json()
        assert len(items) == 2

        one = await client.get(
            f"/api/v1/diagnoses/{second.json()['id']}", headers=viewer
        )
        assert one.status_code == 200
        assert one.json()["id"] == second.json()["id"]

    async def test_get_unknown_diagnosis_is_404(
        self, client, auth_headers, viewer_user
    ) -> None:
        import uuid

        headers = await auth_headers("viewer@example.com")
        response = await client.get(
            f"/api/v1/diagnoses/{uuid.uuid4()}", headers=headers
        )
        assert response.status_code == 404
