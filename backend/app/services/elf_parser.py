"""ELF and MAP file parsing.

Extracts the symbol table, executable section ranges and DWARF line
information from a firmware build so raw crash addresses can be turned back
into function names and source locations.

Pure module: filesystem reads only, no database and no framework. ``pyelftools``
does the work in-process, so no cross toolchain needs to be installed — an
important property when the platform is deployed as a container and the
firmware was built elsewhere.

A GNU ``ld`` map file is supported as a fallback. It carries symbol addresses
but no sizes and no line information, so it yields "which function" without
"which line" — still far better than a bare hex address.
"""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.exceptions import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Symbols below this size carry no useful range; kept but flagged.
MIN_SYMBOL_SIZE = 1

#: A single firmware image should never legitimately exceed this many symbols.
MAX_SYMBOLS = 200_000


class ArtifactKind(StrEnum):
    ELF = "elf"
    MAP = "map"


class ElfParseError(ValidationError):
    """Raised when a build artifact cannot be read."""

    error_code = "elf_parse_error"
    message = "The firmware artifact could not be parsed."


@dataclass(slots=True, frozen=True)
class Symbol:
    """A function or object symbol with its address range."""

    name: str
    address: int
    size: int
    kind: str = "func"
    section: str | None = None

    @property
    def end_address(self) -> int:
        """Exclusive upper bound. Zero-sized symbols cover one byte."""
        return self.address + max(self.size, MIN_SYMBOL_SIZE)

    def contains(self, address: int) -> bool:
        return self.address <= address < self.end_address


@dataclass(slots=True, frozen=True)
class SectionRange:
    """An address range from the ELF section table."""

    name: str
    start: int
    size: int
    executable: bool

    @property
    def end(self) -> int:
        return self.start + self.size

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end


@dataclass(slots=True)
class ElfInfo:
    """Everything extracted from one build artifact."""

    kind: ArtifactKind
    arch: str | None = None
    entry_point: int | None = None
    has_dwarf: bool = False
    build_id: str | None = None
    symbols: list[Symbol] = field(default_factory=list)
    sections: list[SectionRange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def executable_ranges(self) -> list[SectionRange]:
        return [section for section in self.sections if section.executable]

    @property
    def function_symbols(self) -> list[Symbol]:
        return [symbol for symbol in self.symbols if symbol.kind == "func"]


# ---------------------------------------------------------------------------
# ARM Thumb helpers
# ---------------------------------------------------------------------------
def normalize_thumb_address(address: int) -> int:
    """Clear the Thumb state bit from a code address.

    On Cortex-M every instruction is Thumb, so function pointers and the
    return addresses pushed in ``LR`` carry bit 0 set to mean "stay in Thumb
    state". That bit is not part of the address: looking up ``0x08001A2D``
    in the symbol table finds nothing, while ``0x08001A2C`` finds the function.
    """
    return address & ~1


def is_thumb_address(address: int) -> bool:
    """True when bit 0 is set, which marks a Thumb code address."""
    return bool(address & 1)


def is_arm_arch(arch: str | None) -> bool:
    """True for an ARM machine architecture.

    The Thumb-bit convention is ARM-specific: an ARM Thumb function symbol has
    bit 0 of ``st_value`` set, while DWARF records the even instruction
    address. Clearing the bit reconciles the two. On other architectures a
    function address may legitimately be odd (functions are byte-aligned on
    x86), so clearing bit 0 there corrupts the address and breaks line lookup.
    """
    return bool(arch and "ARM" in arch.upper())


# ---------------------------------------------------------------------------
# ELF
# ---------------------------------------------------------------------------
class ElfParser:
    """Reads symbols and section layout from an ELF file."""

    def parse(self, path: Path | str) -> ElfInfo:
        """Parse the ELF at ``path``.

        Raises:
            ElfParseError: the file is missing, not an ELF, or unreadable.
        """
        file_path = Path(path)
        if not file_path.is_file():
            raise ElfParseError(f"Artifact not found: {file_path.name}")

        try:
            from elftools.common.exceptions import ELFError
            from elftools.elf.elffile import ELFFile
        except ImportError as exc:  # pragma: no cover - declared dependency
            raise ElfParseError("pyelftools is not installed on the server.") from exc

        info = ElfInfo(kind=ArtifactKind.ELF)

        try:
            with file_path.open("rb") as handle:
                elf = ELFFile(handle)
                info.arch = elf.get_machine_arch()
                info.entry_point = elf.header.get("e_entry")
                info.has_dwarf = elf.has_dwarf_info()
                info.sections = list(self._read_sections(elf))
                info.build_id = self._read_build_id(elf)
                info.symbols = list(self._read_symbols(elf, info))
        except ELFError as exc:
            raise ElfParseError(f"Not a valid ELF file: {exc}") from exc
        except OSError as exc:
            raise ElfParseError(f"Could not read artifact: {exc}") from exc

        if not info.symbols:
            info.warnings.append("no symbol table found - the build may have been stripped")
        if not info.has_dwarf:
            info.warnings.append("no DWARF debug info - source file and line will be unavailable")
        logger.info(
            "elf.parsed",
            arch=info.arch,
            symbols=len(info.symbols),
            dwarf=info.has_dwarf,
        )
        return info

    @staticmethod
    def _read_sections(elf: Any) -> Iterator[SectionRange]:
        """Yield allocated sections, flagging the executable ones.

        Executable ranges are what makes stack-trace reconstruction possible:
        a stack word is only a plausible return address if it points into
        code.
        """
        for section in elf.iter_sections():
            header = section.header
            flags = header.get("sh_flags", 0)
            if not flags & 0x2:  # SHF_ALLOC - not resident at runtime
                continue
            address = header.get("sh_addr", 0)
            size = header.get("sh_size", 0)
            if not size:
                continue
            yield SectionRange(
                name=section.name,
                start=address,
                size=size,
                executable=bool(flags & 0x4),  # SHF_EXECINSTR
            )

    @staticmethod
    def _read_build_id(elf: Any) -> str | None:
        """Return the GNU build id, which uniquely identifies the binary."""
        section = elf.get_section_by_name(".note.gnu.build-id")
        if section is None:
            return None
        try:
            for note in section.iter_notes():
                if note.get("n_type") == "NT_GNU_BUILD_ID":
                    description = note["n_desc"]
                    if isinstance(description, bytes):
                        return description.hex()
                    return str(description)
        except Exception as exc:  # noqa: BLE001 - a bad note must not fail the upload
            logger.warning("elf.build_id_unreadable", error=str(exc))
        return None

    @staticmethod
    def _read_symbols(elf: Any, info: ElfInfo) -> Iterator[Symbol]:
        """Yield function and object symbols from ``.symtab`` or ``.dynsym``."""
        table = elf.get_section_by_name(".symtab") or elf.get_section_by_name(".dynsym")
        if table is None:
            return

        # Only clear the Thumb bit on ARM; elsewhere an odd address is real.
        clear_thumb = is_arm_arch(info.arch)

        seen: set[tuple[str, int]] = set()
        count = 0
        for symbol in table.iter_symbols():
            entry = symbol.entry
            symbol_type = entry["st_info"]["type"]
            if symbol_type not in ("STT_FUNC", "STT_OBJECT"):
                continue
            name = symbol.name
            if not name:
                continue

            raw = int(entry["st_value"])
            address = normalize_thumb_address(raw) if clear_thumb else raw
            if address == 0:
                continue

            key = (name, address)
            if key in seen:
                continue
            seen.add(key)

            count += 1
            if count > MAX_SYMBOLS:
                info.warnings.append(f"symbol table truncated at {MAX_SYMBOLS} entries")
                return

            yield Symbol(
                name=name,
                address=address,
                size=int(entry["st_size"]),
                kind="func" if symbol_type == "STT_FUNC" else "object",
                section=None,
            )


# ---------------------------------------------------------------------------
# MAP files
# ---------------------------------------------------------------------------
#: Matches a GNU ld map line such as
#:     0x0000000008001a2c                vTaskDelay
_MAP_SYMBOL = re.compile(r"^\s+0x(?P<address>[0-9a-fA-F]{8,16})\s+(?P<name>[A-Za-z_.$][\w.$]*)\s*$")


class MapParser:
    """Reads symbol addresses from a GNU ``ld`` map file.

    A map file has no symbol sizes, so each symbol's range is inferred by
    running to the start of the next one. That is exactly how a linker map is
    read by hand, and it is accurate except at the final symbol.
    """

    def parse(self, path: Path | str) -> ElfInfo:
        file_path = Path(path)
        if not file_path.is_file():
            raise ElfParseError(f"Artifact not found: {file_path.name}")

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ElfParseError(f"Could not read artifact: {exc}") from exc

        return self.parse_text(text)

    def parse_text(self, text: str) -> ElfInfo:
        info = ElfInfo(kind=ArtifactKind.MAP)
        collected: dict[int, str] = {}

        for line in text.splitlines():
            match = _MAP_SYMBOL.match(line)
            if match is None:
                continue
            address = normalize_thumb_address(int(match.group("address"), 16))
            if address == 0:
                continue
            # A later definition at the same address is usually an alias; keep
            # the first, which is the primary name.
            collected.setdefault(address, match.group("name"))

        addresses = sorted(collected)
        for index, address in enumerate(addresses):
            next_address = addresses[index + 1] if index + 1 < len(addresses) else None
            size = (next_address - address) if next_address else 0
            info.symbols.append(
                Symbol(name=collected[address], address=address, size=size, kind="func")
            )

        if not info.symbols:
            raise ElfParseError("No symbols found in the map file. Is this a GNU ld map?")
        info.warnings.append(
            "map files carry no line information - source locations will be unavailable"
        )
        info.warnings.append("symbol sizes inferred from the next symbol's address")
        logger.info("map.parsed", symbols=len(info.symbols))
        return info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def detect_kind(filename: str, head: bytes) -> ArtifactKind:
    """Classify an uploaded artifact by magic bytes, then by extension.

    Content wins over the filename: an ELF named ``firmware.map`` is still an
    ELF, and treating it as text would silently produce zero symbols.
    """
    if head.startswith(b"\x7fELF"):
        return ArtifactKind.ELF
    suffix = Path(filename).suffix.lower()
    if suffix in (".map", ".txt"):
        return ArtifactKind.MAP
    if suffix in (".elf", ".axf", ".out", ""):
        return ArtifactKind.ELF
    return ArtifactKind.MAP


def parse_artifact(path: Path | str, kind: ArtifactKind) -> ElfInfo:
    """Parse ``path`` using the parser for ``kind``."""
    if kind == ArtifactKind.ELF:
        return ElfParser().parse(path)
    return MapParser().parse(path)


def file_sha256(path: Path | str, *, chunk_size: int = 1 << 20) -> str:
    """Content hash of an artifact, used to detect a re-upload of the same build."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_address_index(symbols: list[Symbol]) -> tuple[list[int], list[Symbol]]:
    """Return ``(sorted_addresses, symbols)`` for binary-search lookup."""
    ordered = sorted(symbols, key=lambda symbol: (symbol.address, -symbol.size))
    return [symbol.address for symbol in ordered], ordered


def lookup_symbol(address: int, addresses: list[int], symbols: list[Symbol]) -> Symbol | None:
    """Find the symbol covering ``address`` via binary search.

    ``addresses`` and ``symbols`` come from :func:`build_address_index`.
    Returns ``None`` when the address falls past the end of the nearest
    symbol, which usually means the address is in a different build.
    """
    if not addresses:
        return None
    index = bisect_right(addresses, address) - 1
    if index < 0:
        return None
    candidate = symbols[index]
    return candidate if candidate.contains(address) else None
