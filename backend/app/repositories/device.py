"""Device, tag and API-key repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload

from app.models.device import Device, DeviceApiKey, Tag
from app.repositories.base import BaseRepository, affected_rows


class DeviceRepository(BaseRepository[Device]):
    model = Device

    #: Relationships every read of a device needs.
    _EAGER = (selectinload(Device.tags), selectinload(Device.owner))

    async def get_full(self, device_id: uuid.UUID) -> Device | None:
        stmt = select(Device).where(Device.id == device_id).options(*self._EAGER)
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_identifier(self, identifier: str) -> Device | None:
        """Resolve a device by its firmware ``device_id`` or its serial number.

        Devices report whichever of the two their build was flashed with, so
        ingestion accepts either.
        """
        cleaned = identifier.strip()
        stmt = (
            select(Device)
            .where(or_(Device.device_id == cleaned, Device.serial_number == cleaned))
            .options(*self._EAGER)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def identifier_taken(
        self, *, device_id: str | None = None, serial_number: str | None = None
    ) -> bool:
        conditions = []
        if device_id:
            conditions.append(Device.device_id == device_id.strip())
        if serial_number:
            conditions.append(Device.serial_number == serial_number.strip())
        if not conditions:
            return False
        stmt = select(func.count()).select_from(Device).where(or_(*conditions))
        return int((await self.session.execute(stmt)).scalar_one()) > 0

    async def search(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        firmware_version: str | None = None,
        hardware_model: str | None = None,
        tag: str | None = None,
        owner_id: uuid.UUID | None = None,
        online_since: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Device], int]:
        """Filtered, paginated device listing. Returns ``(items, total)``."""
        conditions = []

        if query:
            pattern = f"%{query.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Device.device_id).like(pattern),
                    func.lower(Device.serial_number).like(pattern),
                    func.lower(Device.hardware_model).like(pattern),
                    func.lower(func.coalesce(Device.location, "")).like(pattern),
                    func.lower(func.coalesce(Device.description, "")).like(pattern),
                )
            )
        if status:
            conditions.append(Device.status == status)
        if firmware_version:
            conditions.append(Device.firmware_version == firmware_version)
        if hardware_model:
            conditions.append(Device.hardware_model == hardware_model)
        if owner_id:
            conditions.append(Device.owner_id == owner_id)
        if online_since:
            conditions.append(Device.last_online_at >= online_since)

        stmt = select(Device).options(*self._EAGER)
        count_stmt = select(func.count(func.distinct(Device.id))).select_from(Device)

        if tag:
            normalized = Tag.normalize(tag)
            stmt = stmt.join(Device.tags).where(Tag.name == normalized)
            count_stmt = count_stmt.join(Device.tags).where(Tag.name == normalized)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(Device.created_at.desc()).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().unique().all()
        return items, total

    async def touch_last_online(
        self, device_id: uuid.UUID, *, when: datetime | None = None
    ) -> None:
        """Record a check-in without loading the row."""
        stmt = (
            update(Device)
            .where(Device.id == device_id)
            .values(last_online_at=when or datetime.now(UTC))
        )
        await self.session.execute(stmt)

    async def count_by_status(self) -> dict[str, int]:
        """Device counts grouped by status, for the dashboard."""
        stmt = select(Device.status, func.count()).group_by(Device.status)
        rows = (await self.session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}


class TagRepository(BaseRepository[Tag]):
    model = Tag

    async def get_or_create_many(self, names: Sequence[str]) -> list[Tag]:
        """Resolve tag names to rows, creating any that do not exist yet.

        Tags are a shared vocabulary: two devices labelled "field-trial" point
        at the same row, so renaming or listing tags stays a single operation.
        """
        normalized = []
        for name in names:
            tag = Tag.normalize(name)
            if tag and tag not in normalized:
                normalized.append(tag)
        if not normalized:
            return []

        existing = (
            (await self.session.execute(select(Tag).where(Tag.name.in_(normalized))))
            .scalars()
            .all()
        )
        by_name = {tag.name: tag for tag in existing}

        for name in normalized:
            if name not in by_name:
                created = Tag(name=name)
                self.session.add(created)
                by_name[name] = created

        await self.session.flush()
        return [by_name[name] for name in normalized]

    async def list_with_counts(self) -> list[tuple[Tag, int]]:
        """Every tag with the number of devices carrying it."""
        stmt = (
            select(Tag, func.count(Device.id))
            .outerjoin(Tag.devices)
            .group_by(Tag.id)
            .order_by(Tag.name)
        )
        return [(tag, int(count)) for tag, count in (await self.session.execute(stmt)).all()]


class DeviceApiKeyRepository(BaseRepository[DeviceApiKey]):
    model = DeviceApiKey

    async def get_by_prefix(self, prefix: str) -> DeviceApiKey | None:
        """Look a key up by its non-secret prefix.

        The prefix narrows the search to one row; the caller then verifies the
        secret against the stored hash.
        """
        stmt = (
            select(DeviceApiKey)
            .where(DeviceApiKey.prefix == prefix)
            .options(selectinload(DeviceApiKey.device))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_device(self, device_id: uuid.UUID) -> list[DeviceApiKey]:
        stmt = (
            select(DeviceApiKey)
            .where(DeviceApiKey.device_id == device_id)
            .order_by(DeviceApiKey.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def revoke(self, key: DeviceApiKey) -> None:
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            await self.session.flush()

    async def revoke_all_for_device(self, device_id: uuid.UUID) -> int:
        stmt = (
            update(DeviceApiKey)
            .where(DeviceApiKey.device_id == device_id, DeviceApiKey.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return affected_rows(await self.session.execute(stmt))

    async def touch_last_used(self, key_id: uuid.UUID) -> None:
        stmt = (
            update(DeviceApiKey)
            .where(DeviceApiKey.id == key_id)
            .values(last_used_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)
