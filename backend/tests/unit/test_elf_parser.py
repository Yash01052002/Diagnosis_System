"""Unit tests for the ELF and MAP parsers.

These run against a real ELF compiled by the ``elf_fixture`` session fixture,
so they exercise the same pyelftools paths production will meet rather than a
hand-rolled stand-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.elf_parser import (
    ArtifactKind,
    ElfParseError,
    ElfParser,
    MapParser,
    Symbol,
    build_address_index,
    detect_kind,
    file_sha256,
    is_thumb_address,
    lookup_symbol,
    normalize_thumb_address,
)


class TestThumbHelpers:
    def test_normalize_clears_low_bit(self) -> None:
        assert normalize_thumb_address(0x08001A2D) == 0x08001A2C
        assert normalize_thumb_address(0x08001A2C) == 0x08001A2C

    def test_is_thumb_detects_low_bit(self) -> None:
        assert is_thumb_address(0x08001A2D)
        assert not is_thumb_address(0x08001A2C)


class TestElfParsing:
    def test_parses_symbols_and_arch(self, elf_fixture: Path) -> None:
        info = ElfParser().parse(elf_fixture)

        assert info.kind is ArtifactKind.ELF
        assert info.arch
        assert info.symbols
        names = {symbol.name for symbol in info.function_symbols}
        assert {"helper_add", "compute_checksum", "sensor_task_body"} <= names

    def test_reports_dwarf_and_sections(self, elf_fixture: Path) -> None:
        info = ElfParser().parse(elf_fixture)

        assert info.has_dwarf, "the fixture is compiled with -g"
        assert info.executable_ranges, "at least .text must be executable"
        assert all(section.executable for section in info.executable_ranges)

    def test_arm_thumb_bit_cleared_only_on_arm(self) -> None:
        """ARM function symbols are Thumb-tagged; other arches keep raw addresses."""
        from app.services.elf_parser import is_arm_arch

        assert is_arm_arch("ARM")
        assert is_arm_arch("ARMv7")
        assert not is_arm_arch("x64")
        assert not is_arm_arch(None)

    def test_non_arm_addresses_are_preserved(self, elf_fixture: Path) -> None:
        """On x86 a function address may be odd; the parser must not corrupt it."""
        info = ElfParser().parse(elf_fixture)

        assert info.function_symbols
        assert all(symbol.address > 0 for symbol in info.function_symbols)

    def test_missing_file_is_rejected(self) -> None:
        with pytest.raises(ElfParseError, match="not found"):
            ElfParser().parse("/nonexistent/firmware.elf")

    def test_non_elf_is_rejected(self, tmp_path: Path) -> None:
        junk = tmp_path / "not.elf"
        junk.write_bytes(b"this is definitely not an ELF file")

        with pytest.raises(ElfParseError, match="valid ELF"):
            ElfParser().parse(junk)


class TestMapParsing:
    #: A minimal GNU ld map snippet.
    MAP_TEXT = """
Memory Configuration

Linker script and memory map

 .text           0x0000000008000000     0x1a40
                 0x0000000008000000                vTaskStartScheduler
                 0x0000000008001a2c                vTaskDelay
                 0x0000000008001a40                xQueueSend
 .data           0x0000000020000000       0x80
"""

    def test_parses_symbols(self) -> None:
        info = MapParser().parse_text(self.MAP_TEXT)

        assert info.kind is ArtifactKind.MAP
        names = {symbol.name for symbol in info.symbols}
        assert {"vTaskStartScheduler", "vTaskDelay", "xQueueSend"} <= names

    def test_infers_sizes_from_next_symbol(self) -> None:
        info = MapParser().parse_text(self.MAP_TEXT)
        by_name = {symbol.name: symbol for symbol in info.symbols}

        # vTaskDelay runs from 0x08001a2c to the next symbol at 0x08001a40.
        assert by_name["vTaskDelay"].size == 0x14

    def test_warns_about_missing_line_info(self) -> None:
        info = MapParser().parse_text(self.MAP_TEXT)

        assert any("line information" in warning for warning in info.warnings)

    def test_empty_map_is_rejected(self) -> None:
        with pytest.raises(ElfParseError, match="No symbols"):
            MapParser().parse_text("no symbols here\njust prose\n")


class TestDetectKind:
    def test_elf_magic_wins_over_extension(self) -> None:
        assert detect_kind("firmware.map", b"\x7fELF\x02\x01\x01") is ArtifactKind.ELF

    def test_map_extension(self) -> None:
        assert detect_kind("firmware.map", b"\nMemory Config") is ArtifactKind.MAP

    @pytest.mark.parametrize("name", ["fw.elf", "fw.axf", "fw.out", "fw"])
    def test_elf_extensions(self, name: str) -> None:
        assert detect_kind(name, b"random") is ArtifactKind.ELF


class TestAddressIndex:
    def _symbols(self) -> list[Symbol]:
        return [
            Symbol(name="a", address=0x1000, size=0x40),
            Symbol(name="b", address=0x1040, size=0x40),
            Symbol(name="c", address=0x1080, size=0x10),
        ]

    def test_lookup_finds_covering_symbol(self) -> None:
        addresses, symbols = build_address_index(self._symbols())

        assert lookup_symbol(0x1020, addresses, symbols).name == "a"
        assert lookup_symbol(0x1040, addresses, symbols).name == "b"
        assert lookup_symbol(0x1088, addresses, symbols).name == "c"

    def test_lookup_past_last_symbol_returns_none(self) -> None:
        addresses, symbols = build_address_index(self._symbols())

        # 0x10A0 is past the end of "c" (ends at 0x1090).
        assert lookup_symbol(0x10A0, addresses, symbols) is None

    def test_lookup_before_first_symbol_returns_none(self) -> None:
        addresses, symbols = build_address_index(self._symbols())

        assert lookup_symbol(0x500, addresses, symbols) is None

    def test_empty_index(self) -> None:
        assert lookup_symbol(0x1000, [], []) is None


class TestFileHash:
    def test_hash_is_stable_and_content_based(self, tmp_path: Path) -> None:
        first = tmp_path / "a.bin"
        second = tmp_path / "b.bin"
        first.write_bytes(b"identical content")
        second.write_bytes(b"identical content")

        assert file_sha256(first) == file_sha256(second)
        assert len(file_sha256(first)) == 64
