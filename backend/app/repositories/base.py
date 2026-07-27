"""Generic asynchronous repository.

The repository pattern keeps persistence concerns out of the service layer:
services speak in domain terms ("get the user with this email") and never
build SQL. Concrete repositories subclass :class:`BaseRepository` and add
query methods specific to their aggregate.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import CursorResult, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


def affected_rows(result: Any) -> int:
    """Rows touched by a bulk UPDATE/DELETE.

    ``Session.execute`` is typed as returning ``Result``; only the
    ``CursorResult`` returned by DML statements exposes ``rowcount``.
    """
    return int(cast(CursorResult[Any], result).rowcount or 0)


class BaseRepository(Generic[ModelT]):
    """CRUD operations shared by every aggregate."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- reads ---------------------------------------------------------
    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_by(self, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: Any | None = None,
        **filters: Any,
    ) -> Sequence[ModelT]:
        stmt: Select[tuple[ModelT]] = select(self.model).filter_by(**filters)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def exists(self, **filters: Any) -> bool:
        return await self.count(**filters) > 0

    # -- writes --------------------------------------------------------
    def add(self, entity: ModelT) -> ModelT:
        """Stage a new entity. The caller controls the transaction boundary."""
        self.session.add(entity)
        return entity

    async def create(self, **values: Any) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelT, **values: Any) -> ModelT:
        for key, value in values.items():
            setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def delete_by_id(self, entity_id: uuid.UUID) -> int:
        stmt = delete(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return affected_rows(result)
