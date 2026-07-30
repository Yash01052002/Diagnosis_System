"""End-to-end tests for symbolication and crash grouping.

The scenario throughout: a device reports a crash whose addresses point into
functions defined in the compiled ELF fixture. With the matching build indexed,
those addresses must resolve to function names and source lines, and identical
crashes must collapse into one group.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import CrashReport
from app.repositories.build import BuildSymbolRepository, FirmwareBuildRepository
from app.repositories.crash import CrashReportRepository
from app.repositories.crash_group import CrashGroupRepository
from app.services.symbolication import SymbolicationService

pytestmark = pytest.mark.asyncio


def _service(session: AsyncSession, settings: Settings) -> SymbolicationService:
    return SymbolicationService(
        session=session,
        crashes=CrashReportRepository(session),
        builds=FirmwareBuildRepository(session),
        symbols=BuildSymbolRepository(session),
        groups=CrashGroupRepository(session),
        settings=settings,
    )


async def _make_crash(
    session: AsyncSession,
    device,  # noqa: ANN001
    *,
    pc: int,
    lr: int | None = None,
    stack: list[int] | None = None,
    fault_type: str = "hard_fault",
    task_name: str = "SensorTask",
    firmware_version: str = "1.4.2",
    occurred_at: datetime | None = None,
) -> CrashReport:
    when = occurred_at or datetime.now(UTC)
    report = CrashReport(
        device_id=device.id,
        firmware_version=firmware_version,
        build_version="a1b2c3d",
        occurred_at=when,
        received_at=when,
        fault_type=fault_type,
        task_name=task_name,
        program_counter=pc,
        link_register=lr,
        stack_dump={"start_address": None, "words": stack or []},
        severity="critical",
        status="new",
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


class TestSymbolicationWithBuild:
    async def test_resolves_functions_and_lines(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            lr=elf_symbols["compute_checksum"] + 8,
            firmware_version=device.firmware_version,
        )

        outcome = await _service(db_session, settings).symbolicate(crash.id)

        assert outcome.result.symbolized
        assert outcome.result.pc.function == "helper_add"
        assert outcome.result.pc.source_file.endswith("fw.c")
        assert outcome.result.pc.line is not None
        assert outcome.result.lr.function == "compute_checksum"

    async def test_stores_symbolication_on_report(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        build = await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )

        await _service(db_session, settings).symbolicate(crash.id)
        await db_session.refresh(crash)

        assert crash.symbolicated_at is not None
        assert crash.top_function == "helper_add"
        assert crash.build_id == build.id
        assert crash.symbolication["symbolized"] is True

    async def test_reconstructs_stack_frames(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            stack=[
                0x20000100,  # junk data pointer
                elf_symbols["compute_checksum"] + 0x20,
                elf_symbols["sensor_task_body"] + 0x10,
            ],
            firmware_version=device.firmware_version,
        )

        outcome = await _service(db_session, settings).symbolicate(crash.id)

        functions = [f.function for f in outcome.result.frames if f.resolved]
        assert "helper_add" in functions
        assert "compute_checksum" in functions
        assert "sensor_task_body" in functions


class TestGrouping:
    async def test_identical_crashes_share_a_group(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        first_device = await device_factory()
        second_device = await device_factory()
        await build_factory(firmware_version=first_device.firmware_version)
        service = _service(db_session, settings)

        crash_a = await _make_crash(
            db_session,
            first_device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=first_device.firmware_version,
        )
        crash_b = await _make_crash(
            db_session,
            second_device,
            pc=elf_symbols["helper_add"] + 8,
            firmware_version=second_device.firmware_version,
        )

        out_a = await service.symbolicate(crash_a.id)
        out_b = await service.symbolicate(crash_b.id)

        assert out_a.signature == out_b.signature
        assert out_a.group.id == out_b.group.id
        assert out_b.group.occurrence_count == 2
        assert out_b.group.device_count == 2, "two distinct devices"

    async def test_same_device_twice_counts_one_device(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        service = _service(db_session, settings)

        crash_a = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        crash_b = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 8,
            occurred_at=datetime.now(UTC) + timedelta(minutes=5),
            firmware_version=device.firmware_version,
        )

        await service.symbolicate(crash_a.id)
        out_b = await service.symbolicate(crash_b.id)

        assert out_b.group.occurrence_count == 2
        assert out_b.group.device_count == 1

    async def test_different_faults_form_different_groups(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        service = _service(db_session, settings)

        crash_a = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            fault_type="hard_fault",
            firmware_version=device.firmware_version,
        )
        crash_b = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["compute_checksum"] + 4,
            fault_type="bus_fault",
            firmware_version=device.firmware_version,
        )

        out_a = await service.symbolicate(crash_a.id)
        out_b = await service.symbolicate(crash_b.id)

        assert out_a.group.id != out_b.group.id

    async def test_group_carries_worst_severity(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        service = _service(db_session, settings)

        low = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        low.severity = "low"
        await db_session.commit()
        await service.symbolicate(low.id)

        high = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 8,
            occurred_at=datetime.now(UTC) + timedelta(minutes=1),
            firmware_version=device.firmware_version,
        )
        high.severity = "critical"
        await db_session.commit()
        out = await service.symbolicate(high.id)

        assert out.group.severity == "critical"


class TestDegradation:
    async def test_no_build_still_groups(
        self, db_session: AsyncSession, settings: Settings, device_factory
    ) -> None:
        """Without an ELF the crash is unresolved but still gets a signature."""
        device = await device_factory()
        crash = await _make_crash(db_session, device, pc=0x08001A2C)

        outcome = await _service(db_session, settings).symbolicate(crash.id)

        assert not outcome.result.symbolized
        assert outcome.signature
        assert outcome.group is not None
        assert any("no indexed firmware build" in w for w in outcome.result.warnings)

    async def test_late_build_upgrades_crashes(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        """A crash stored before its ELF existed is upgraded when it arrives."""
        device = await device_factory()
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        service = _service(db_session, settings)

        # First pass: no build, unresolved.
        before = await service.symbolicate(crash.id)
        assert not before.result.symbolized

        # The ELF arrives; re-symbolize.
        await build_factory(firmware_version=device.firmware_version)
        result = await service.resymbolicate_for_build(
            firmware_version=device.firmware_version, build_version="a1b2c3d"
        )

        assert result["upgraded"] == 1
        await db_session.refresh(crash)
        assert crash.top_function == "helper_add"

    async def test_missing_artifact_resolves_names_only(
        self,
        db_session: AsyncSession,
        settings: Settings,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        """Symbols come from the DB, so names survive a pruned artifact file."""
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version, copy_artifact=False)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )

        outcome = await _service(db_session, settings).symbolicate(crash.id)

        assert outcome.result.pc.function == "helper_add"
        assert outcome.result.pc.line is None, "no file on disk, so no line"
        assert any("no longer on disk" in w for w in outcome.result.warnings)


class TestIngestionIntegration:
    async def test_ingested_crash_is_symbolicated(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        device_factory,
        api_key_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        """The full path: submit a crash, and it comes back symbolized."""
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        api_key = await api_key_factory(device)

        response = await client.post(
            "/api/v1/crashes",
            json={
                "firmware_version": device.firmware_version,
                "build_version": "a1b2c3d",
                "fault_type": "HardFault",
                "task_name": "SensorTask",
                "pc": hex(elf_symbols["helper_add"] + 4),
            },
            headers={"X-API-Key": api_key},
        )

        assert response.status_code == 201, response.text
        crash_id = response.json()["id"]
        stored = (
            await db_session.execute(
                select(CrashReport).where(CrashReport.id == uuid.UUID(crash_id))
            )
        ).scalar_one()
        assert stored.top_function == "helper_add"
        assert stored.group_id is not None


class TestGroupsAPI:
    async def test_group_listed_after_symbolication(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        settings: Settings,
        auth_headers,
        viewer_user,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        await _service(db_session, settings).symbolicate(crash.id)
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/crash-groups", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["top_function"] == "helper_add"
        assert "helper_add" in body["items"][0]["title"]

    async def test_engineer_triages_group(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        settings: Settings,
        auth_headers,
        engineer_user,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        group = (await _service(db_session, settings).symbolicate(crash.id)).group
        headers = await auth_headers(engineer_user.email)

        response = await client.patch(
            f"/api/v1/crash-groups/{group.id}",
            json={"status": "resolved", "notes": "fixed in 1.5.0"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["status"] == "resolved"

    async def test_group_regresses_when_crash_returns(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        settings: Settings,
        auth_headers,
        engineer_user,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        """A resolved bug that crashes again flips to regressed automatically."""
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        service = _service(db_session, settings)

        first = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        group = (await service.symbolicate(first.id)).group
        group.status = "resolved"
        await db_session.commit()

        later = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 8,
            occurred_at=datetime.now(UTC) + timedelta(hours=1),
            firmware_version=device.firmware_version,
        )
        out = await service.symbolicate(later.id)

        assert out.group.status == "regressed"
        assert out.group.regressed_at is not None

    async def test_group_crashes_endpoint(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        settings: Settings,
        auth_headers,
        viewer_user,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        group = (await _service(db_session, settings).symbolicate(crash.id)).group
        headers = await auth_headers(viewer_user.email)

        response = await client.get(f"/api/v1/crash-groups/{group.id}/crashes", headers=headers)

        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_top_groups_endpoint(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        settings: Settings,
        auth_headers,
        viewer_user,
        device_factory,
        build_factory,
        elf_symbols: dict[str, int],
    ) -> None:
        device = await device_factory()
        await build_factory(firmware_version=device.firmware_version)
        crash = await _make_crash(
            db_session,
            device,
            pc=elf_symbols["helper_add"] + 4,
            firmware_version=device.firmware_version,
        )
        await _service(db_session, settings).symbolicate(crash.id)
        headers = await auth_headers(viewer_user.email)

        response = await client.get("/api/v1/crash-groups/top?limit=5", headers=headers)

        assert response.status_code == 200
        assert len(response.json()) == 1
