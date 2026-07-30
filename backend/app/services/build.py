"""Firmware build artifact management.

Handles upload, storage, symbol extraction and indexing of ELF/MAP files.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.audit_log import AuditAction
from app.models.build import ArtifactType, BuildStatus, FirmwareBuild
from app.models.user import User
from app.repositories.build import BuildSymbolRepository, FirmwareBuildRepository
from app.services.audit import AuditService
from app.services.auth import RequestContext
from app.services.elf_parser import (
    ElfInfo,
    ElfParseError,
    detect_kind,
    file_sha256,
    parse_artifact,
)

logger = get_logger(__name__)

#: Bytes read to sniff the file type before committing it to storage.
MAGIC_BYTES = 16


class BuildService:
    """Use-cases for firmware build artifacts."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        builds: FirmwareBuildRepository,
        symbols: BuildSymbolRepository,
        audit: AuditService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.builds = builds
        self.symbols = symbols
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, build_id: uuid.UUID) -> FirmwareBuild:
        build = await self.builds.get_full(build_id)
        if build is None:
            raise NotFoundError("Firmware build not found.")
        return build

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
        return await self.builds.search(
            query=query,
            firmware_version=firmware_version,
            build_version=build_version,
            status=status,
            artifact_type=artifact_type,
            offset=offset,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    async def upload(
        self,
        *,
        stream: BinaryIO,
        filename: str,
        firmware_version: str,
        build_version: str | None = None,
        hardware_model: str | None = None,
        notes: str | None = None,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> FirmwareBuild:
        """Store an artifact, extract its symbols and index them.

        Indexing runs inline rather than in a worker: it takes well under a
        second for a typical firmware image, and an engineer uploading an ELF
        wants to know immediately whether it was usable. Re-indexing an
        existing build is available as a Celery task.

        Raises:
            ValidationError: the file is empty, too large, or unparsable.
        """
        ctx = ctx or RequestContext()

        temp_path = self._spool_to_disk(stream, filename)
        try:
            head = temp_path.open("rb").read(MAGIC_BYTES)
            kind = detect_kind(filename, head)
            info = self._parse_or_fail(temp_path, kind, filename)

            digest = file_sha256(temp_path)
            artifact_type = ArtifactType.ELF if kind.value == ArtifactType.ELF else ArtifactType.MAP

            # Re-uploading the same (firmware, build, type) replaces the old
            # artifact: a rebuilt image legitimately supersedes its predecessor,
            # and keeping both would make symbolization ambiguous.
            existing = await self.builds.get_by_identity(
                firmware_version=firmware_version,
                build_version=build_version,
                artifact_type=artifact_type,
            )
            if existing is not None:
                await self._replace_artifact(existing, temp_path, digest, filename, info)
                build = existing
            else:
                build = await self._create_build(
                    temp_path=temp_path,
                    digest=digest,
                    filename=filename,
                    firmware_version=firmware_version,
                    build_version=build_version,
                    hardware_model=hardware_model,
                    notes=notes,
                    artifact_type=artifact_type,
                    info=info,
                    actor=actor,
                )

            await self._index_symbols(build, info)

            await self.audit.record(
                AuditAction.BUILD_UPLOADED,
                actor_id=actor.id,
                actor_email=actor.email,
                resource_type="firmware_build",
                resource_id=build.id,
                ip_address=ctx.ip_address,
                user_agent=ctx.user_agent,
                context={
                    "firmware_version": firmware_version,
                    "build_version": build_version,
                    "artifact_type": artifact_type,
                    "symbols": build.symbol_count,
                    "replaced": existing is not None,
                },
            )
            await self.session.commit()
            logger.info(
                "build.indexed",
                build_id=str(build.id),
                firmware_version=firmware_version,
                symbols=build.symbol_count,
                dwarf=build.has_debug_info,
            )
            return await self.get(build.id)
        finally:
            temp_path.unlink(missing_ok=True)

    def _spool_to_disk(self, stream: BinaryIO, filename: str) -> Path:
        """Write the upload to a temp file, enforcing the size limit.

        Streamed in chunks and checked as it goes, so an oversized upload is
        rejected without ever being held in memory.
        """
        limit = self.settings.max_artifact_bytes
        written = 0
        temp = NamedTemporaryFile(  # noqa: SIM115 - closed explicitly below
            delete=False, dir=self.settings.artifact_dir, suffix=".upload"
        )
        temp_path = Path(temp.name)
        try:
            while chunk := stream.read(1 << 20):
                written += len(chunk)
                if written > limit:
                    raise ValidationError(
                        f"Artifact exceeds the {self.settings.MAX_ARTIFACT_SIZE_MB} MB limit.",
                        details={"filename": filename},
                    )
                temp.write(chunk)
        except Exception:
            temp.close()
            temp_path.unlink(missing_ok=True)
            raise
        temp.close()

        if written == 0:
            temp_path.unlink(missing_ok=True)
            raise ValidationError("Artifact is empty.", details={"filename": filename})
        return temp_path

    @staticmethod
    def _parse_or_fail(path: Path, kind: object, filename: str) -> ElfInfo:
        try:
            return parse_artifact(path, kind)  # type: ignore[arg-type]
        except ElfParseError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a 422, not a 500
            raise ValidationError(
                f"Could not parse {filename}: {exc}", details={"filename": filename}
            ) from exc

    async def _create_build(
        self,
        *,
        temp_path: Path,
        digest: str,
        filename: str,
        firmware_version: str,
        build_version: str | None,
        hardware_model: str | None,
        notes: str | None,
        artifact_type: str,
        info: ElfInfo,
        actor: User,
    ) -> FirmwareBuild:
        build = FirmwareBuild(
            firmware_version=firmware_version,
            build_version=build_version,
            hardware_model=hardware_model,
            artifact_type=artifact_type,
            original_filename=Path(filename).name[:255],
            storage_path="",  # set below, once the id is known
            file_size=temp_path.stat().st_size,
            sha256=digest,
            build_id=info.build_id,
            status=BuildStatus.INDEXING,
            arch=info.arch,
            has_debug_info=info.has_dwarf,
            entry_point=info.entry_point,
            notes=notes,
            uploaded_by_id=actor.id,
        )
        self.builds.add(build)
        await self.session.flush()

        build.storage_path = str(self._store_artifact(temp_path, build.id, filename))
        return build

    async def _replace_artifact(
        self,
        build: FirmwareBuild,
        temp_path: Path,
        digest: str,
        filename: str,
        info: ElfInfo,
    ) -> None:
        """Swap in a new artifact for an existing build row."""
        self._remove_stored_file(build)
        await self.symbols.delete_for_build(build.id)

        build.storage_path = str(self._store_artifact(temp_path, build.id, filename))
        build.original_filename = Path(filename).name[:255]
        build.file_size = temp_path.stat().st_size
        build.sha256 = digest
        build.build_id = info.build_id
        build.arch = info.arch
        build.has_debug_info = info.has_dwarf
        build.entry_point = info.entry_point
        build.status = BuildStatus.INDEXING
        build.error_message = None
        await self.session.flush()

    def _store_artifact(self, temp_path: Path, build_id: uuid.UUID, filename: str) -> Path:
        """Move the spooled upload to its permanent path.

        Named by build id rather than by the uploaded filename, so a hostile
        or merely careless name cannot escape the storage directory.
        """
        suffix = Path(filename).suffix.lower()[:10]
        destination = self.settings.artifact_dir / f"{build_id}{suffix}"
        shutil.move(str(temp_path), destination)
        # Recreate the temp path so the caller's unlink() is harmless.
        temp_path.touch(exist_ok=True)
        return destination

    async def _index_symbols(self, build: FirmwareBuild, info: ElfInfo) -> None:
        """Persist the extracted symbol table and section ranges."""
        symbols = info.symbols[: self.settings.MAX_INDEXED_SYMBOLS]
        truncated = len(info.symbols) > len(symbols)

        await self.symbols.bulk_insert(build.id, symbols)

        warnings = list(info.warnings)
        if truncated:
            warnings.append(
                f"symbol table truncated to {self.settings.MAX_INDEXED_SYMBOLS} entries"
            )

        build.symbol_count = len(symbols)
        build.sections = {
            "sections": [
                {
                    "name": section.name,
                    "start": section.start,
                    "size": section.size,
                    "executable": section.executable,
                }
                for section in info.sections
            ]
        }
        build.parse_warnings = {"warnings": warnings} if warnings else None
        build.status = BuildStatus.INDEXED if symbols else BuildStatus.FAILED
        build.error_message = None if symbols else "No symbols found in the artifact."
        build.indexed_at = datetime.now(UTC)
        await self.session.flush()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    async def delete(
        self, build_id: uuid.UUID, *, actor: User, ctx: RequestContext | None = None
    ) -> None:
        """Delete a build, its symbols and its stored artifact.

        Crash reports that referenced it keep their stored symbolication —
        ``build_id`` is ``ON DELETE SET NULL``. Removing the build removes the
        ability to symbolize *new* crashes, not the results already recorded.
        """
        ctx = ctx or RequestContext()
        build = await self.get(build_id)

        await self.audit.record(
            AuditAction.BUILD_DELETED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="firmware_build",
            resource_id=build.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={
                "firmware_version": build.firmware_version,
                "build_version": build.build_version,
                "symbols": build.symbol_count,
            },
        )
        self._remove_stored_file(build)
        await self.builds.delete(build)
        await self.session.commit()
        logger.info("build.deleted", build_id=str(build_id))

    @staticmethod
    def _remove_stored_file(build: FirmwareBuild) -> None:
        if not build.storage_path:
            return
        try:
            Path(build.storage_path).unlink(missing_ok=True)
        except OSError as exc:  # noqa: BLE001 - a stale file must not block the delete
            logger.warning("build.artifact_unlink_failed", path=build.storage_path, error=str(exc))
