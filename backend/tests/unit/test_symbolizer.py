"""Unit tests for the symbolizer and stack analyzer.

Run against the real compiled ELF, so DWARF line resolution, section-based
candidate filtering and signature stability are all exercised end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.elf_parser import ElfParser, SectionRange
from app.services.stack_analyzer import (
    build_signature,
    build_title,
    looks_like_return_address,
    normalize_function_name,
    reconstruct_stack,
)
from app.services.symbolizer import ResolvedFrame, Symbolizer


@pytest.fixture
def symbolizer(elf_fixture: Path) -> Symbolizer:
    info = ElfParser().parse(elf_fixture)
    # The fixture ELF is x86-64, whose function addresses may be odd; Thumb
    # normalization would corrupt them, so it is disabled to match the parser.
    return Symbolizer(
        info.symbols,
        elf_path=elf_fixture,
        build_version="test-build",
        normalize_thumb="ARM" in (info.arch or "").upper(),
    )


@pytest.fixture
def exec_ranges(elf_fixture: Path) -> list[SectionRange]:
    return ElfParser().parse(elf_fixture).executable_ranges


class TestSymbolResolution:
    def test_resolves_function_and_offset(
        self, symbolizer: Symbolizer, elf_symbols: dict[str, int]
    ) -> None:
        target = elf_symbols["helper_add"] + 4
        frame = symbolizer.resolve(target, origin="pc")

        assert frame.function == "helper_add"
        assert frame.offset == 4
        assert frame.resolved

    def test_resolves_source_line_from_dwarf(
        self, symbolizer: Symbolizer, elf_symbols: dict[str, int]
    ) -> None:
        frame = symbolizer.resolve(elf_symbols["helper_add"])

        assert frame.source_file is not None
        assert frame.source_file.endswith("fw.c")
        assert frame.line is not None

    def test_thumb_bit_address_still_resolves(
        self, symbolizer: Symbolizer, elf_symbols: dict[str, int]
    ) -> None:
        frame = symbolizer.resolve(elf_symbols["helper_add"] | 1)

        assert frame.function == "helper_add"
        assert frame.thumb

    def test_unknown_address_degrades(self, symbolizer: Symbolizer) -> None:
        frame = symbolizer.resolve(0x7FDEADBE)

        assert not frame.resolved
        assert frame.function is None
        assert frame.display == "0x7FDEADBE"

    def test_display_format(self, symbolizer: Symbolizer, elf_symbols: dict[str, int]) -> None:
        frame = symbolizer.resolve(elf_symbols["helper_add"] + 4)

        assert frame.function in frame.display
        assert "fw.c:" in frame.display


class TestReturnAddressFilter:
    def _ranges(self) -> list[SectionRange]:
        return [SectionRange(name=".text", start=0x08000000, size=0x2000, executable=True)]

    def test_thumb_code_address_accepted(self) -> None:
        assert looks_like_return_address(0x08001A2D, self._ranges())

    def test_non_thumb_rejected_when_required(self) -> None:
        assert not looks_like_return_address(0x08001A2C, self._ranges(), require_thumb=True)

    def test_data_pointer_rejected(self) -> None:
        # In range value but points outside executable memory.
        assert not looks_like_return_address(0x20000101, self._ranges())

    def test_small_integer_rejected(self) -> None:
        assert not looks_like_return_address(0x00000043, self._ranges())

    def test_without_ranges_only_thumb_checked(self) -> None:
        assert looks_like_return_address(0x08001A2D, [])
        assert not looks_like_return_address(0x08001A2C, [], require_thumb=True)


class TestStackReconstruction:
    def test_orders_pc_lr_then_stack(
        self,
        symbolizer: Symbolizer,
        exec_ranges: list[SectionRange],
        elf_symbols: dict[str, int],
    ) -> None:
        analysis = reconstruct_stack(
            [elf_symbols["sensor_task_body"] + 0x10],
            symbolizer,
            executable_ranges=exec_ranges,
            program_counter=elf_symbols["helper_add"] + 4,
            link_register=elf_symbols["compute_checksum"] + 8,
            require_thumb=False,
        )

        origins = [frame.origin for frame in analysis.frames]
        assert origins[0] == "pc"
        assert origins[1] == "lr"
        assert "stack" in origins

    def test_filters_junk_from_stack(
        self,
        symbolizer: Symbolizer,
        exec_ranges: list[SectionRange],
        elf_symbols: dict[str, int],
    ) -> None:
        stack = [
            0x20017FB0,  # data pointer - rejected
            elf_symbols["compute_checksum"] + 0x20,  # real
            0x00000042,  # small int - rejected
            0xFFFFFFFD,  # EXC_RETURN - rejected
        ]
        analysis = reconstruct_stack(
            stack, symbolizer, executable_ranges=exec_ranges, require_thumb=False
        )

        resolved = [f for f in analysis.frames if f.resolved]
        assert any(f.function == "compute_checksum" for f in resolved)
        assert len(analysis.candidate_addresses) == 1

    def test_collapses_adjacent_duplicates(
        self,
        symbolizer: Symbolizer,
        exec_ranges: list[SectionRange],
        elf_symbols: dict[str, int],
    ) -> None:
        address = elf_symbols["helper_add"] + 4
        analysis = reconstruct_stack(
            [address, address, address],
            symbolizer,
            executable_ranges=exec_ranges,
            require_thumb=False,
        )

        assert len(analysis.frames) == 1

    def test_max_frames_is_respected(
        self, symbolizer: Symbolizer, exec_ranges: list[SectionRange], elf_symbols: dict[str, int]
    ) -> None:
        # Alternate two addresses so none are adjacent duplicates.
        a = elf_symbols["helper_add"] + 4
        b = elf_symbols["compute_checksum"] + 4
        stack = [a if i % 2 else b for i in range(20)]

        analysis = reconstruct_stack(
            stack, symbolizer, executable_ranges=exec_ranges, require_thumb=False, max_frames=5
        )

        assert len(analysis.frames) == 5

    def test_no_candidates_warns(
        self, symbolizer: Symbolizer, exec_ranges: list[SectionRange]
    ) -> None:
        analysis = reconstruct_stack(
            [0x11111110, 0x22222220],
            symbolizer,
            executable_ranges=exec_ranges,
            require_thumb=False,
        )

        assert not analysis.candidate_addresses
        assert any("no plausible" in w for w in analysis.warnings)


class TestSignatures:
    def _frames(self, *names: str) -> list[ResolvedFrame]:
        return [
            ResolvedFrame(address=0x1000 + i, function=name, resolved=True)
            for i, name in enumerate(names)
        ]

    def test_signature_is_stable(self) -> None:
        frames = self._frames("vTaskDelay", "prvIdleTask")
        first, _ = build_signature(fault_type="hard_fault", task_name="IDLE", frames=frames)
        second, _ = build_signature(fault_type="hard_fault", task_name="IDLE", frames=frames)

        assert first == second
        assert len(first) == 32

    def test_same_bug_matches_across_builds(self) -> None:
        """Names, not addresses, so a rebuild does not change the signature."""
        build_a = [ResolvedFrame(address=0x08001000, function="vTaskDelay", resolved=True)]
        build_b = [ResolvedFrame(address=0x08009999, function="vTaskDelay", resolved=True)]

        sig_a, _ = build_signature(fault_type="hard_fault", task_name="T", frames=build_a)
        sig_b, _ = build_signature(fault_type="hard_fault", task_name="T", frames=build_b)

        assert sig_a == sig_b

    def test_different_functions_differ(self) -> None:
        a, _ = build_signature(fault_type="hard_fault", task_name="T", frames=self._frames("foo"))
        b, _ = build_signature(fault_type="hard_fault", task_name="T", frames=self._frames("bar"))

        assert a != b

    def test_different_fault_types_differ(self) -> None:
        frames = self._frames("foo")
        a, _ = build_signature(fault_type="hard_fault", task_name="T", frames=frames)
        b, _ = build_signature(fault_type="bus_fault", task_name="T", frames=frames)

        assert a != b

    def test_clone_suffixes_are_stripped(self) -> None:
        a, _ = build_signature(
            fault_type="hard_fault", task_name="T", frames=self._frames("process.constprop.0")
        )
        b, _ = build_signature(
            fault_type="hard_fault", task_name="T", frames=self._frames("process")
        )

        assert a == b

    def test_unsymbolized_falls_back_to_pc_and_firmware(self) -> None:
        """No frames: signature is build-scoped, and records why."""
        sig, components = build_signature(
            fault_type="hard_fault",
            task_name="T",
            frames=[],
            program_counter=0x08001A2C,
            firmware_version="1.4.2",
        )

        assert sig
        assert components["symbolized"] is False
        assert components["firmware_version"] == "1.4.2"

    def test_unsymbolized_differs_by_firmware(self) -> None:
        a, _ = build_signature(
            fault_type="hard_fault",
            task_name="T",
            frames=[],
            program_counter=0x08001A2C,
            firmware_version="1.4.2",
        )
        b, _ = build_signature(
            fault_type="hard_fault",
            task_name="T",
            frames=[],
            program_counter=0x08001A2C,
            firmware_version="2.0.0",
        )

        assert a != b, "same address in different builds is a different location"


class TestTitleAndNames:
    def test_title_uses_innermost_function(self) -> None:
        frames = [
            ResolvedFrame(address=0x1000, function="vTaskDelay", resolved=True),
            ResolvedFrame(address=0x1040, function="prvIdleTask", resolved=True),
        ]

        assert build_title(fault_type="hard_fault", frames=frames) == "hard fault in vTaskDelay"

    def test_title_falls_back_to_task(self) -> None:
        assert (
            build_title(fault_type="watchdog_reset", frames=[], task_name="SensorTask")
            == "watchdog reset in task SensorTask"
        )

    def test_title_bare_fault(self) -> None:
        assert build_title(fault_type="hard_fault", frames=[]) == "hard fault"

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("foo.constprop.0", "foo"),
            ("foo.isra.3", "foo"),
            ("foo.part.1", "foo"),
            ("foo.cold", "foo"),
            ("plain_name", "plain_name"),
        ],
    )
    def test_normalize_function_name(self, name: str, expected: str) -> None:
        assert normalize_function_name(name) == expected
