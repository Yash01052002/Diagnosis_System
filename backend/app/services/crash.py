"""Crash report ingestion and triage."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.audit_log import AuditAction
from app.models.crash import CrashReport, CrashStatus
from app.models.device import Device
from app.models.user import User
from app.repositories.crash import CrashReportRepository
from app.repositories.device import DeviceRepository
from app.schemas.crash import CrashReportUpdate
from app.services.audit import AuditService
from app.services.auth import RequestContext
from app.services.crash_parser import CrashParser, ParsedCrash
from app.services.symbolication import SymbolicationService

logger = get_logger(__name__)


@dataclass(slots=True)
class IngestResult:
    """Outcome of an ingestion attempt."""

    report: CrashReport
    warnings: list[str]
    #: True when the payload matched a report already stored, in which case
    #: ``report`` is the existing row and nothing new was written.
    duplicate: bool = False


class CrashService:
    """Ingestion, retrieval and triage of crash reports."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        crashes: CrashReportRepository,
        devices: DeviceRepository,
        audit: AuditService,
        parser: CrashParser,
        symbolication: SymbolicationService | None = None,
    ) -> None:
        self.session = session
        self.crashes = crashes
        self.devices = devices
        self.audit = audit
        self.parser = parser
        #: Optional so the ingestion path can be tested without a symbol store.
        self.symbolication = symbolication

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    async def ingest(
        self,
        payload: Mapping[str, Any],
        *,
        device: Device | None = None,
        actor: User | None = None,
        ctx: RequestContext | None = None,
    ) -> IngestResult:
        """Parse, validate and store a crash report.

        Args:
            payload: Raw JSON from the device.
            device: Pre-resolved device when an API key identified it. When
                omitted, the device is looked up from the payload.
            actor: The user submitting on a device's behalf, if any.
            ctx: Client metadata for the audit entry.

        Raises:
            CrashParseError: the payload could not be parsed.
            NotFoundError: the payload names a device that is not registered.
            ValidationError: no device could be determined at all.
        """
        ctx = ctx or RequestContext()
        received_at = datetime.now(UTC)

        try:
            parsed = self.parser.parse(payload, now=received_at)
        except ValidationError as exc:
            await self._record_rejection(
                reason=exc.message, payload=payload, device=device, actor=actor, ctx=ctx
            )
            raise

        target = device or await self._resolve_device(parsed, payload, actor, ctx)

        # A device that just reported a crash is, by definition, online.
        await self.devices.touch_last_online(target.id, when=received_at)

        existing = await self.crashes.find_recent_duplicate(
            device_id=target.id,
            fault_type=parsed.fault_type,
            program_counter=parsed.program_counter,
            occurred_at=parsed.occurred_at,
        )
        if existing is not None:
            await self.session.commit()
            logger.info(
                "crash.duplicate_ignored",
                device_id=target.device_id,
                crash_id=str(existing.id),
            )
            return IngestResult(
                report=existing,
                warnings=[*parsed.warnings, "duplicate of a report received moments ago"],
                duplicate=True,
            )

        report = CrashReport(
            device_id=target.id,
            firmware_version=parsed.firmware_version,
            build_version=parsed.build_version,
            occurred_at=parsed.occurred_at,
            received_at=received_at,
            fault_type=parsed.fault_type,
            exception_type=parsed.exception_type,
            task_name=parsed.task_name,
            program_counter=parsed.program_counter,
            link_register=parsed.link_register,
            stack_pointer=parsed.stack_pointer,
            register_dump=parsed.register_dump,
            stack_dump=parsed.stack_dump,
            severity=parsed.severity,
            status=CrashStatus.NEW,
            notes=parsed.notes,
            raw_payload=dict(payload),
            parse_warnings={"warnings": parsed.warnings} if parsed.warnings else None,
            parser_version=parsed.parser_version,
        )
        self.crashes.add(report)
        await self.session.flush()

        await self.audit.record(
            AuditAction.CRASH_RECEIVED,
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            resource_type="crash_report",
            resource_id=report.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={
                "device_id": target.device_id,
                "fault_type": str(parsed.fault_type),
                "severity": str(parsed.severity),
                "warnings": len(parsed.warnings),
            },
        )
        await self.session.commit()

        # Symbolize and group before acknowledging. It is a symbol-table lookup
        # against an already-loaded build, not a heavy job, and a report that
        # arrives without a group would otherwise be invisible in the grouped
        # views until something else swept it up.
        if self.symbolication is not None:
            try:
                await self.symbolication.symbolicate_report(report)
            except Exception as exc:  # noqa: BLE001
                # Ingestion must never fail because symbolization did: the
                # report is already stored, and it can be symbolized later.
                logger.warning(
                    "crash.symbolication_failed",
                    crash_id=str(report.id),
                    error=str(exc),
                )
                await self.session.rollback()

        logger.info(
            "crash.ingested",
            crash_id=str(report.id),
            device_id=target.device_id,
            fault_type=str(parsed.fault_type),
            severity=str(parsed.severity),
        )
        return IngestResult(report=await self.get(report.id), warnings=parsed.warnings)

    async def _resolve_device(
        self,
        parsed: ParsedCrash,
        payload: Mapping[str, Any],
        actor: User | None,
        ctx: RequestContext,
    ) -> Device:
        """Find the device named in the payload.

        Only reached when no API key identified the sender, i.e. an engineer
        submitting on a device's behalf.
        """
        if not parsed.device_identifier:
            await self._record_rejection(
                reason="device identifier missing",
                payload=payload,
                device=None,
                actor=actor,
                ctx=ctx,
            )
            raise ValidationError(
                "device_id is required when not authenticating with a device API key.",
                details={"field": "device_id"},
            )

        device = await self.devices.get_by_identifier(parsed.device_identifier)
        if device is None:
            await self._record_rejection(
                reason="unknown device",
                payload=payload,
                device=None,
                actor=actor,
                ctx=ctx,
                extra={"device_identifier": parsed.device_identifier},
            )
            raise NotFoundError(
                f"No device registered with identifier {parsed.device_identifier!r}. "
                "Register the device before submitting crash reports.",
                details={"device_id": parsed.device_identifier},
            )
        return device

    async def _record_rejection(
        self,
        *,
        reason: str,
        payload: Mapping[str, Any],
        device: Device | None,
        actor: User | None,
        ctx: RequestContext,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Audit a rejected report.

        Rejections are recorded because a firmware build that suddenly starts
        sending unparsable reports is itself a defect worth seeing.
        """
        await self.audit.record(
            AuditAction.CRASH_REJECTED,
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            resource_type="crash_report",
            resource_id=device.id if device else None,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            success=False,
            context={
                "reason": reason,
                "payload_keys": sorted(payload.keys())[:20],
                **(extra or {}),
            },
        )
        await self.session.commit()
        logger.warning("crash.rejected", reason=reason, **(extra or {}))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get(self, crash_id: uuid.UUID) -> CrashReport:
        report = await self.crashes.get_full(crash_id)
        if report is None:
            raise NotFoundError("Crash report not found.")
        return report

    async def search(
        self,
        *,
        device_id: uuid.UUID | None = None,
        device_identifier: str | None = None,
        group_id: uuid.UUID | None = None,
        firmware_version: str | None = None,
        build_version: str | None = None,
        fault_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        task_name: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        query: str | None = None,
        diagnosed: bool | None = None,
        symbolicated: bool | None = None,
        offset: int = 0,
        limit: int = 20,
        sort: str = "-occurred_at",
    ) -> tuple[Sequence[CrashReport], int]:
        """Filtered, paginated crash history. Returns ``(items, total)``."""
        return await self.crashes.search(
            device_id=device_id,
            device_identifier=device_identifier,
            group_id=group_id,
            firmware_version=firmware_version,
            build_version=build_version,
            fault_type=fault_type,
            severity=severity,
            status=status,
            task_name=task_name,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            query=query,
            diagnosed=diagnosed,
            symbolicated=symbolicated,
            offset=offset,
            limit=limit,
            sort=sort,
        )

    # ------------------------------------------------------------------
    # Triage
    # ------------------------------------------------------------------
    async def update(
        self,
        crash_id: uuid.UUID,
        payload: CrashReportUpdate,
        *,
        actor: User,
        ctx: RequestContext | None = None,
    ) -> CrashReport:
        """Apply engineer triage. Fault evidence is never mutated."""
        ctx = ctx or RequestContext()
        report = await self.get(crash_id)
        data = payload.model_dump(exclude_unset=True)
        changed: dict[str, object] = {}

        for attribute in ("status", "severity", "notes"):
            if attribute in data:
                value = data[attribute]
                setattr(report, attribute, value)
                changed[attribute] = str(value) if value is not None else None

        if not changed:
            raise ValidationError("No changes supplied.")

        await self.session.flush()
        await self.audit.record(
            AuditAction.CRASH_UPDATED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="crash_report",
            resource_id=report.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={"changed": list(changed.keys()), **changed},
        )
        await self.session.commit()
        return await self.get(report.id)

    async def delete(
        self, crash_id: uuid.UUID, *, actor: User, ctx: RequestContext | None = None
    ) -> None:
        ctx = ctx or RequestContext()
        report = await self.get(crash_id)

        await self.audit.record(
            AuditAction.CRASH_DELETED,
            actor_id=actor.id,
            actor_email=actor.email,
            resource_type="crash_report",
            resource_id=report.id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            context={
                "device_id": report.device.device_id if report.device else None,
                "fault_type": report.fault_type,
                "occurred_at": report.occurred_at.isoformat(),
            },
        )
        await self.crashes.delete(report)
        await self.session.commit()
