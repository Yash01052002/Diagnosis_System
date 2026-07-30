"""Firmware build and symbol repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import selectinload

from app.models.build import BuildStatus, BuildSymbol, FirmwareBuild
from app.repositories.base import BaseRepository, affected_rows
from app.services.elf_parser import Symbol


class FirmwareBuildRepository(BaseRepository[FirmwareBuild]):
    model = FirmwareBuild

    _EAGER = (selectinload(FirmwareBuild.uploaded_by),)

    async def get_full(self, build_id: uuid.UUID) -> FirmwareBuild | None:
        stmt = select(FirmwareBuild).where(FirmwareBuild.id == build_id).options(*self._EAGER)
        return (await self.session.execute(stmt)).scalars().first()

    async def find_for_crash(
        self, *, firmware_version: str, build_version: str | None
    ) -> FirmwareBuild | None:
        """Find the artifact that can symbolize a crash.

        Matching is deliberately ordered by specificity:

        1. Exact ``(firmware_version, build_version)`` — unambiguous.
        2. ``firmware_version`` alone, when the crash reported no build.
        3. Nothing — the crash stays unsymbolized rather than being resolved
           against a build it did not come from, which would produce
           confidently wrong function names.

        An ELF is preferred over a MAP at equal specificity, because only the
        ELF carries line information.
        """
        base = select(FirmwareBuild).where(
            FirmwareBuild.firmware_version == firmware_version,
            FirmwareBuild.status == BuildStatus.INDEXED,
            FirmwareBuild.symbol_count > 0,
        )
        # ELF (artifact_type "elf") sorts before "map" alphabetically, and the
        # newest upload wins among equals.
        ordering = (FirmwareBuild.artifact_type.asc(), FirmwareBuild.created_at.desc())

        if build_version:
            exact = base.where(FirmwareBuild.build_version == build_version).order_by(*ordering)
            found = (await self.session.execute(exact.limit(1))).scalars().first()
            if found is not None:
                return found

        fallback = base.where(FirmwareBuild.build_version.is_(None)).order_by(*ordering)
        found = (await self.session.execute(fallback.limit(1))).scalars().first()
        if found is not None:
            return found

        # Last resort: any indexed artifact for this firmware version.
        any_build = base.order_by(*ordering)
        return (await self.session.execute(any_build.limit(1))).scalars().first()

    async def get_by_identity(
        self, *, firmware_version: str, build_version: str | None, artifact_type: str
    ) -> FirmwareBuild | None:
        """Find an existing row for the unique (firmware, build, type) triple."""
        stmt = select(FirmwareBuild).where(
            FirmwareBuild.firmware_version == firmware_version,
            FirmwareBuild.artifact_type == artifact_type,
            FirmwareBuild.build_version == build_version
            if build_version
            else FirmwareBuild.build_version.is_(None),
        )
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    async def search(
        self,
        *,
        query: str | None = None,
        firmware_version: str | None = None,
        build_version: str | None = None,
        status: str | None = None,
        artifact_type: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[FirmwareBuild], int]:
        conditions = []
        if firmware_version:
            conditions.append(FirmwareBuild.firmware_version == firmware_version)
        if build_version:
            conditions.append(FirmwareBuild.build_version == build_version)
        if status:
            conditions.append(FirmwareBuild.status == status)
        if artifact_type:
            conditions.append(FirmwareBuild.artifact_type == artifact_type)
        if query:
            pattern = f"%{query.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(FirmwareBuild.firmware_version).like(pattern),
                    func.lower(func.coalesce(FirmwareBuild.build_version, "")).like(pattern),
                    func.lower(FirmwareBuild.original_filename).like(pattern),
                    func.lower(func.coalesce(FirmwareBuild.notes, "")).like(pattern),
                )
            )

        stmt = select(FirmwareBuild).options(*self._EAGER)
        count_stmt = select(func.count()).select_from(FirmwareBuild)
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        total = int((await self.session.execute(count_stmt)).scalar_one())
        stmt = stmt.order_by(FirmwareBuild.created_at.desc()).offset(offset).limit(limit)
        items = (await self.session.execute(stmt)).scalars().unique().all()
        return items, total


class BuildSymbolRepository(BaseRepository[BuildSymbol]):
    model = BuildSymbol

    async def bulk_insert(self, build_id: uuid.UUID, symbols: Sequence[Symbol]) -> int:
        """Insert a build's symbol table.

        Uses a Core bulk insert rather than ORM objects: a firmware image can
        carry tens of thousands of symbols, and instantiating an ORM instance
        per row would dominate the indexing time.
        """
        if not symbols:
            return 0
        rows = [
            {
                "id": uuid.uuid4(),
                "build_id": build_id,
                "name": symbol.name[:255],
                "address": symbol.address,
                "size": symbol.size,
                "kind": symbol.kind,
            }
            for symbol in symbols
        ]
        await self.session.execute(insert(BuildSymbol), rows)
        return len(rows)

    async def delete_for_build(self, build_id: uuid.UUID) -> int:
        stmt = delete(BuildSymbol).where(BuildSymbol.build_id == build_id)
        return affected_rows(await self.session.execute(stmt))

    async def load_symbols(self, build_id: uuid.UUID) -> list[Symbol]:
        """Load a build's symbols as parser dataclasses for the symbolizer."""
        stmt = select(
            BuildSymbol.name, BuildSymbol.address, BuildSymbol.size, BuildSymbol.kind
        ).where(BuildSymbol.build_id == build_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            Symbol(name=name, address=int(address), size=int(size), kind=kind)
            for name, address, size, kind in rows
        ]

    async def count_for_build(self, build_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(BuildSymbol).where(BuildSymbol.build_id == build_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def find_by_name(self, build_id: uuid.UUID, name: str) -> BuildSymbol | None:
        stmt = (
            select(BuildSymbol)
            .where(BuildSymbol.build_id == build_id, BuildSymbol.name == name)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
