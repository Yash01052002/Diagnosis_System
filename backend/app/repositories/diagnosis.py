"""AI diagnosis repository."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.diagnosis import AiDiagnosis
from app.repositories.base import BaseRepository


class AiDiagnosisRepository(BaseRepository[AiDiagnosis]):
    model = AiDiagnosis

    _EAGER = (selectinload(AiDiagnosis.requested_by),)

    async def get_full(self, diagnosis_id: uuid.UUID) -> AiDiagnosis | None:
        stmt = select(AiDiagnosis).where(AiDiagnosis.id == diagnosis_id).options(*self._EAGER)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_crash(self, crash_id: uuid.UUID) -> Sequence[AiDiagnosis]:
        """Diagnosis history for one crash, newest first."""
        stmt = (
            select(AiDiagnosis)
            .where(AiDiagnosis.crash_id == crash_id)
            .options(*self._EAGER)
            .order_by(AiDiagnosis.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_for_group(self, group_id: uuid.UUID) -> Sequence[AiDiagnosis]:
        stmt = (
            select(AiDiagnosis)
            .where(AiDiagnosis.group_id == group_id)
            .options(*self._EAGER)
            .order_by(AiDiagnosis.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def latest_for_crash(self, crash_id: uuid.UUID) -> AiDiagnosis | None:
        stmt = (
            select(AiDiagnosis)
            .where(AiDiagnosis.crash_id == crash_id)
            .options(*self._EAGER)
            .order_by(AiDiagnosis.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
