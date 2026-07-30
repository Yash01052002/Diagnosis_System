"""AI crash-diagnosis endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    DiagnosisServiceDep,
    EngineerUser,
    RequestContextDep,
    require_viewer,
)
from app.schemas.common import ErrorResponse
from app.schemas.knowledge import DiagnosisRead

router = APIRouter(tags=["AI Diagnosis"])


@router.post(
    "/crashes/{crash_id}/diagnose",
    response_model=DiagnosisRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an AI diagnosis for a crash",
    responses={
        404: {"model": ErrorResponse, "description": "Crash report not found"},
    },
)
async def diagnose_crash(
    crash_id: uuid.UUID,
    engineer: EngineerUser,
    service: DiagnosisServiceDep,
    ctx: RequestContextDep,
) -> DiagnosisRead:
    """Diagnose a crash with retrieval-augmented generation.

    The symbolized crash is turned into a query, relevant knowledge-base
    passages are retrieved, and the model is asked to explain the fault **using
    only that context**. The returned confidence is grounded in retrieval
    quality: when nothing relevant is found, the diagnosis comes back
    explicitly `uncertain` rather than invented, and every answer lists the
    sources it was built from.

    Requires the `engineer` role. History is kept, so re-running after adding a
    relevant manual produces a new diagnosis to compare, not a replacement.
    """
    outcome = await service.diagnose_crash(crash_id, actor=engineer, ctx=ctx)
    return DiagnosisRead.from_model(outcome.diagnosis)


@router.get(
    "/crashes/{crash_id}/diagnoses",
    response_model=list[DiagnosisRead],
    dependencies=[Depends(require_viewer)],
    summary="Diagnosis history for a crash",
    responses={404: {"model": ErrorResponse, "description": "Crash report not found"}},
)
async def list_crash_diagnoses(
    crash_id: uuid.UUID,
    service: DiagnosisServiceDep,
) -> list[DiagnosisRead]:
    """Every diagnosis generated for a crash, newest first."""
    history = await service.history_for_crash(crash_id)
    return [DiagnosisRead.from_model(item) for item in history]


@router.get(
    "/diagnoses/{diagnosis_id}",
    response_model=DiagnosisRead,
    dependencies=[Depends(require_viewer)],
    summary="Get a diagnosis",
    responses={404: {"model": ErrorResponse, "description": "Diagnosis not found"}},
)
async def get_diagnosis(
    diagnosis_id: uuid.UUID,
    service: DiagnosisServiceDep,
) -> DiagnosisRead:
    """One diagnosis, including its sources and provenance."""
    return DiagnosisRead.from_model(await service.get(diagnosis_id))
