"""Crash symbolication and grouping.

Takes a stored crash report, finds the matching firmware build, resolves its
addresses into functions and source lines, reconstructs the call chain, then
computes a signature and files the report into a crash group.

Degrades at every step rather than failing:

* no matching build → no frames, but a signature is still computed from the
  fault type, task and program counter, so grouping still works within a build;
* build present but stripped → ``function+offset`` without line numbers;
* artifact file pruned from disk → symbols still resolve from the database,
  only source lines are lost.

A crash report is evidence. Nothing here may discard it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.build import FirmwareBuild
from app.models.crash import CrashReport
from app.models.crash_group import CrashGroup, CrashGroupStatus
from app.repositories.build import BuildSymbolRepository, FirmwareBuildRepository
from app.repositories.crash import CrashReportRepository
from app.repositories.crash_group import CrashGroupRepository
from app.services.elf_parser import SectionRange, is_arm_arch
from app.services.stack_analyzer import (
    build_signature,
    build_title,
    normalize_function_name,
    reconstruct_stack,
)
from app.services.symbolizer import ResolvedFrame, SymbolizationResult, Symbolizer

logger = get_logger(__name__)

#: Severity ordering, so a group keeps the worst severity it has ever seen.
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(slots=True)
class SymbolicationOutcome:
    """What symbolizing one report produced."""

    report: CrashReport
    result: SymbolizationResult
    group: CrashGroup | None
    signature: str
    #: True when the group was created by this call.
    group_created: bool = False


class SymbolicationService:
    """Symbolizes crash reports and maintains crash groups."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        crashes: CrashReportRepository,
        builds: FirmwareBuildRepository,
        symbols: BuildSymbolRepository,
        groups: CrashGroupRepository,
        settings: Settings,
    ) -> None:
        self.session = session
        self.crashes = crashes
        self.builds = builds
        self.symbols = symbols
        self.groups = groups
        self.settings = settings

    # ------------------------------------------------------------------
    async def symbolicate(
        self, crash_id: uuid.UUID, *, commit: bool = True
    ) -> SymbolicationOutcome:
        """Symbolize one report, then group it.

        Safe to run more than once: re-running after a build is uploaded
        upgrades a previously unsymbolized report and moves it to the group its
        symbols now say it belongs to.
        """
        report = await self.crashes.get_full(crash_id)
        if report is None:
            raise NotFoundError("Crash report not found.")
        return await self.symbolicate_report(report, commit=commit)

    async def symbolicate_report(
        self, report: CrashReport, *, commit: bool = True
    ) -> SymbolicationOutcome:
        build = await self.builds.find_for_crash(
            firmware_version=report.firmware_version,
            build_version=report.build_version,
        )
        result = await self._resolve_frames(report, build)

        report.symbolication = result.to_dict()
        report.symbolicated_at = datetime.now(UTC)
        report.build_id = build.id if build else None
        report.top_function = self._top_function(result.frames)

        signature, components = build_signature(
            fault_type=report.fault_type,
            task_name=report.task_name,
            frames=result.frames,
            program_counter=report.program_counter,
            firmware_version=report.firmware_version,
        )
        report.crash_signature = signature

        group, created = await self._assign_group(
            report, signature=signature, components=components, frames=result.frames
        )
        report.group_id = group.id

        await self.session.flush()
        if commit:
            await self.session.commit()

        logger.info(
            "crash.symbolicated",
            crash_id=str(report.id),
            build=str(build.id) if build else None,
            frames=len(result.frames),
            resolved=result.resolved_count,
            signature=signature,
        )
        return SymbolicationOutcome(
            report=report,
            result=result,
            group=group,
            signature=signature,
            group_created=created,
        )

    # ------------------------------------------------------------------
    async def _resolve_frames(
        self, report: CrashReport, build: FirmwareBuild | None
    ) -> SymbolizationResult:
        """Resolve PC, LR and the stack dump against ``build``."""
        result = SymbolizationResult(build_version=build.build_version if build else None)

        stack_words = self._stack_words(report)

        if build is None:
            result.warnings.append(
                f"no indexed firmware build for version {report.firmware_version!r}"
                + (f" build {report.build_version!r}" if report.build_version else "")
                + " - upload an ELF or MAP to symbolize this crash"
            )
            # Without symbols there is nothing to resolve, but the raw
            # addresses are still recorded so the UI can show the chain.
            result.frames = self._raw_frames(report, stack_words)
            result.pc = result.frames[0] if result.frames else None
            return result

        symbols = await self.symbols.load_symbols(build.id)
        if not symbols:
            result.warnings.append("the matched build has no indexed symbols")
            result.frames = self._raw_frames(report, stack_words)
            return result

        artifact = Path(build.storage_path) if build.storage_path else None
        if artifact is not None and not artifact.is_file():
            result.warnings.append(
                "artifact file is no longer on disk - resolving names only, no line numbers"
            )
            artifact = None

        symbolizer = Symbolizer(
            symbols,
            elf_path=artifact,
            build_version=build.build_version,
            addr2line_binary=self.settings.ADDR2LINE_BINARY,
            # Match how the parser stored this build's symbols: it cleared the
            # Thumb bit only for ARM, so runtime addresses follow the same rule.
            normalize_thumb=is_arm_arch(build.arch),
        )

        analysis = reconstruct_stack(
            stack_words,
            symbolizer,
            executable_ranges=self._executable_ranges(build),
            program_counter=report.program_counter,
            link_register=report.link_register,
            require_thumb=self.settings.REQUIRE_THUMB_BIT,
            max_frames=self.settings.MAX_STACK_FRAMES,
        )

        result.frames = analysis.frames
        result.warnings.extend(analysis.warnings)
        result.symbolized = any(frame.resolved for frame in analysis.frames)
        result.pc = next((f for f in analysis.frames if f.origin == "pc"), None)
        result.lr = next((f for f in analysis.frames if f.origin == "lr"), None)

        if not result.symbolized and analysis.frames:
            result.warnings.append(
                "no address matched a symbol - the crash may come from a different build"
            )
        if not build.has_debug_info:
            result.warnings.append("build has no debug info - source file and line unavailable")
        return result

    @staticmethod
    def _stack_words(report: CrashReport) -> list[int]:
        dump = report.stack_dump or {}
        words = dump.get("words") or []
        return [int(word) for word in words if isinstance(word, int)]

    @staticmethod
    def _raw_frames(report: CrashReport, stack_words: Sequence[int]) -> list[ResolvedFrame]:
        """Unresolved frames, so the address chain survives without symbols."""
        frames: list[ResolvedFrame] = []
        if report.program_counter is not None:
            frames.append(ResolvedFrame(address=report.program_counter, origin="pc"))
        if report.link_register is not None:
            frames.append(ResolvedFrame(address=report.link_register, origin="lr"))
        frames.extend(ResolvedFrame(address=word, origin="stack") for word in stack_words[:8])
        return frames

    @staticmethod
    def _executable_ranges(build: FirmwareBuild) -> list[SectionRange]:
        payload = build.sections or {}
        ranges: list[SectionRange] = []
        for entry in payload.get("sections", []):
            if not entry.get("executable"):
                continue
            ranges.append(
                SectionRange(
                    name=str(entry.get("name", "")),
                    start=int(entry.get("start", 0)),
                    size=int(entry.get("size", 0)),
                    executable=True,
                )
            )
        return ranges

    @staticmethod
    def _top_function(frames: Sequence[ResolvedFrame]) -> str | None:
        for frame in frames:
            if frame.resolved and frame.function:
                return normalize_function_name(frame.function)[:255]
        return None

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------
    async def _assign_group(
        self,
        report: CrashReport,
        *,
        signature: str,
        components: dict[str, object],
        frames: Sequence[ResolvedFrame],
    ) -> tuple[CrashGroup, bool]:
        """Find or create the group for ``signature`` and update its counters."""
        previous_group_id = report.group_id
        group = await self.groups.get_by_signature(signature)
        created = False

        if group is None:
            group = CrashGroup(
                signature=signature,
                signature_components=components,
                title=build_title(
                    fault_type=report.fault_type,
                    frames=frames,
                    task_name=report.task_name,
                ),
                fault_type=report.fault_type,
                task_name=report.task_name,
                top_function=self._top_function(frames),
                severity=report.severity,
                status=CrashGroupStatus.OPEN,
                occurrence_count=0,
                device_count=0,
                first_seen_at=report.occurred_at,
                last_seen_at=report.occurred_at,
            )
            self.groups.add(group)
            await self.session.flush()
            created = True

        # Re-symbolication can move a report between groups; the group it left
        # must not keep counting it.
        if previous_group_id and previous_group_id != group.id:
            previous = await self.groups.get(previous_group_id)
            if previous is not None:
                report.group_id = group.id
                await self.session.flush()
                await self.groups.recompute_counters(previous)

        already_counted = previous_group_id == group.id
        if not already_counted:
            group.occurrence_count += 1

        self._widen_window(group, report)
        self._escalate_severity(group, report)
        self._record_firmware_version(group, report)
        self._maybe_regress(group, report)

        # Distinct devices cannot be tracked with a counter, since the same
        # device crashing twice must not count twice.
        report.group_id = group.id
        await self.session.flush()
        group.device_count = await self.groups.distinct_device_count(group.id)

        await self.session.flush()
        return group, created

    @staticmethod
    def _widen_window(group: CrashGroup, report: CrashReport) -> None:
        occurred = _as_utc(report.occurred_at)
        if occurred < _as_utc(group.first_seen_at):
            group.first_seen_at = report.occurred_at
        if occurred > _as_utc(group.last_seen_at):
            group.last_seen_at = report.occurred_at

    @staticmethod
    def _escalate_severity(group: CrashGroup, report: CrashReport) -> None:
        """A group carries the worst severity any of its occurrences reached."""
        current = _SEVERITY_RANK.get(group.severity, 1)
        incoming = _SEVERITY_RANK.get(report.severity, 1)
        if incoming > current:
            group.severity = report.severity

    @staticmethod
    def _record_firmware_version(group: CrashGroup, report: CrashReport) -> None:
        payload = dict(group.affected_firmware_versions or {})
        versions = list(payload.get("versions", []))
        if report.firmware_version not in versions:
            versions.append(report.firmware_version)
            versions.sort(reverse=True)
            payload["versions"] = versions
            # Reassigned rather than mutated: SQLAlchemy does not track
            # in-place changes to a JSON column.
            group.affected_firmware_versions = payload

    @staticmethod
    def _maybe_regress(group: CrashGroup, report: CrashReport) -> None:
        """A resolved group that crashes again has regressed.

        Worth flagging loudly: a fix that did not hold is more urgent than a
        bug nobody has looked at yet.
        """
        if group.status == CrashGroupStatus.RESOLVED:
            group.status = CrashGroupStatus.REGRESSED
            group.regressed_at = datetime.now(UTC)
            logger.warning(
                "crash_group.regressed",
                group_id=str(group.id),
                signature=group.signature,
                firmware_version=report.firmware_version,
            )

    # ------------------------------------------------------------------
    # Bulk re-symbolication
    # ------------------------------------------------------------------
    async def resymbolicate_for_build(
        self, *, firmware_version: str, build_version: str | None = None, limit: int = 500
    ) -> dict[str, int]:
        """Re-run symbolication for crashes matching a newly uploaded build.

        This is what makes a late ELF upload worthwhile: crashes already
        collected are upgraded in place instead of staying as hex forever.
        """
        reports, total = await self.crashes.search(
            firmware_version=firmware_version,
            build_version=build_version,
            limit=limit,
            offset=0,
        )
        upgraded = 0
        for report in reports:
            outcome = await self.symbolicate_report(report, commit=False)
            if outcome.result.symbolized:
                upgraded += 1
        await self.session.commit()

        logger.info(
            "crash.resymbolicated",
            firmware_version=firmware_version,
            processed=len(reports),
            upgraded=upgraded,
            total_matching=total,
        )
        return {
            "processed": len(reports),
            "upgraded": upgraded,
            "total_matching": total,
        }


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
