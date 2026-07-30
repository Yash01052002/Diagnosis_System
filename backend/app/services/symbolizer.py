"""Address symbolization.

Turns a raw crash address into ``function + offset`` and, when DWARF is
available, ``source file:line``.

Three resolution layers, each falling back to the one below:

1. **DWARF via pyelftools** — full ``file:line``, no external toolchain.
2. **Symbol table only** — ``function+0x1c``, which is what a MAP file or a
   build without debug info can give.
3. **Nothing** — the raw address is returned unchanged and flagged
   unresolved, so the UI can still show it.

An external ``addr2line`` binary can be configured as an *enhancement* rather
than a requirement: it resolves inlined frames, which pyelftools does not do
here. Its absence never breaks symbolization.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.elf_parser import (
    Symbol,
    build_address_index,
    is_thumb_address,
    lookup_symbol,
    normalize_thumb_address,
)

logger = get_logger(__name__)

#: Never spend longer than this waiting for an external addr2line.
ADDR2LINE_TIMEOUT_SECONDS = 10


@dataclass(slots=True)
class ResolvedFrame:
    """One symbolized address."""

    address: int
    #: Where the address came from: "pc", "lr", or "stack".
    origin: str = "stack"
    function: str | None = None
    #: Byte offset into the function, which locates the faulting instruction.
    offset: int | None = None
    source_file: str | None = None
    line: int | None = None
    #: True when the address was inside a known function.
    resolved: bool = False
    #: True when the address had the ARM Thumb bit set.
    thumb: bool = False
    #: Set when the frame came from an inlined function.
    inlined: bool = False

    @property
    def address_hex(self) -> str:
        return f"0x{self.address:08X}"

    @property
    def display(self) -> str:
        """Human-readable one-liner, e.g. ``vTaskDelay+0x1c at tasks.c:1432``."""
        if not self.function:
            return self.address_hex
        text = self.function
        if self.offset:
            text += f"+0x{self.offset:X}"
        if self.source_file:
            location = self.source_file
            if self.line:
                location += f":{self.line}"
            text += f" at {location}"
        return text

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["address_hex"] = self.address_hex
        data["display"] = self.display
        return data


@dataclass(slots=True)
class SymbolizationResult:
    """The symbolized view of one crash."""

    frames: list[ResolvedFrame] = field(default_factory=list)
    pc: ResolvedFrame | None = None
    lr: ResolvedFrame | None = None
    warnings: list[str] = field(default_factory=list)
    #: Which build's symbols were used, if any.
    build_version: str | None = None
    symbolized: bool = False

    @property
    def resolved_count(self) -> int:
        return sum(1 for frame in self.frames if frame.resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbolized": self.symbolized,
            "build_version": self.build_version,
            "pc": self.pc.to_dict() if self.pc else None,
            "lr": self.lr.to_dict() if self.lr else None,
            "frames": [frame.to_dict() for frame in self.frames],
            "resolved_count": self.resolved_count,
            "frame_count": len(self.frames),
            "warnings": self.warnings,
        }


class Symbolizer:
    """Resolves addresses against one build's symbol table.

    Construct with the symbols for a build; pass ``elf_path`` as well to get
    source lines from DWARF.
    """

    def __init__(
        self,
        symbols: list[Symbol],
        *,
        elf_path: Path | str | None = None,
        build_version: str | None = None,
        addr2line_binary: str | None = None,
        normalize_thumb: bool = True,
    ) -> None:
        self._addresses, self._symbols = build_address_index(symbols)
        self.elf_path = Path(elf_path) if elf_path else None
        self.build_version = build_version
        self.addr2line_binary = addr2line_binary
        # Must match how the symbol table was stored: an ARM build cleared the
        # Thumb bit at parse time, so runtime addresses are cleared too; a
        # non-ARM build kept raw addresses, so clearing here would mismatch.
        self.normalize_thumb = normalize_thumb
        self._line_lookup: _DwarfLineTable | None = None
        self._dwarf_attempted = False

    # ------------------------------------------------------------------
    def resolve(self, address: int, *, origin: str = "stack") -> ResolvedFrame:
        """Resolve a single address."""
        thumb = is_thumb_address(address)
        clean = normalize_thumb_address(address) if self.normalize_thumb else address
        frame = ResolvedFrame(address=clean, origin=origin, thumb=thumb)

        symbol = lookup_symbol(clean, self._addresses, self._symbols)
        if symbol is None:
            return frame

        frame.function = symbol.name
        frame.offset = clean - symbol.address
        frame.resolved = True

        location = self._resolve_line(clean)
        if location is not None:
            frame.source_file, frame.line = location
        return frame

    def resolve_many(self, addresses: list[int], *, origin: str = "stack") -> list[ResolvedFrame]:
        return [self.resolve(address, origin=origin) for address in addresses]

    # ------------------------------------------------------------------
    def _resolve_line(self, address: int) -> tuple[str, int] | None:
        """Look up ``file:line`` for ``address``, preferring external addr2line."""
        if self.addr2line_binary:
            location = self._addr2line(address)
            if location is not None:
                return location

        table = self._dwarf_table()
        if table is None:
            return None
        return table.lookup(address)

    def _dwarf_table(self) -> _DwarfLineTable | None:
        """Build the DWARF line table once, on first use."""
        if self._dwarf_attempted:
            return self._line_lookup
        self._dwarf_attempted = True
        if self.elf_path is None or not self.elf_path.is_file():
            return None
        try:
            self._line_lookup = _DwarfLineTable(self.elf_path)
        except Exception as exc:  # noqa: BLE001 - degrade to symbols only
            logger.warning("symbolizer.dwarf_unavailable", error=str(exc))
            self._line_lookup = None
        return self._line_lookup

    def _addr2line(self, address: int) -> tuple[str, int] | None:
        """Shell out to an external addr2line, if one is configured."""
        if self.elf_path is None or not self.elf_path.is_file():
            return None
        try:
            completed = subprocess.run(  # noqa: S603 - binary comes from config
                [
                    self.addr2line_binary or "addr2line",
                    "-e",
                    str(self.elf_path),
                    "-f",
                    "-C",
                    hex(address),
                ],
                capture_output=True,
                text=True,
                timeout=ADDR2LINE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("symbolizer.addr2line_failed", error=str(exc))
            return None

        if completed.returncode != 0:
            return None

        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        location = lines[1]
        if location.startswith("??"):
            return None
        file_part, _, line_part = location.rpartition(":")
        if not file_part:
            return None
        # addr2line appends " (discriminator N)" on optimised builds.
        line_part = line_part.split(" ")[0]
        try:
            return file_part, int(line_part)
        except ValueError:
            return None


class _DwarfLineTable:
    """Flattened DWARF line program: sorted addresses to ``(file, line)``.

    Built once per ELF and cached. Reading the line program lazily per address
    would re-scan every compilation unit for each frame, which for a dozen
    frames is an order of magnitude more work.
    """

    def __init__(self, elf_path: Path) -> None:
        self._addresses: list[int] = []
        self._entries: list[tuple[str, int]] = []
        self._load(elf_path)

    def _load(self, elf_path: Path) -> None:
        from elftools.elf.elffile import ELFFile

        rows: list[tuple[int, str, int]] = []
        with elf_path.open("rb") as handle:
            elf = ELFFile(handle)
            if not elf.has_dwarf_info():
                return
            dwarf = elf.get_dwarf_info()
            for unit in dwarf.iter_CUs():
                program = dwarf.line_program_for_CU(unit)
                if program is None:
                    continue
                file_names = self._file_names(program)
                for entry in program.get_entries():
                    state = entry.state
                    if state is None or state.end_sequence:
                        continue
                    name = file_names.get(state.file, "")
                    if not name:
                        continue
                    rows.append((state.address, name, state.line))

        rows.sort(key=lambda row: row[0])
        self._addresses = [row[0] for row in rows]
        self._entries = [(row[1], row[2]) for row in rows]

    @staticmethod
    def _file_names(program: Any) -> dict[int, str]:
        """Map file indices to names across DWARF 2-4 and DWARF 5.

        DWARF 5 made the file table 0-based and put the primary source file at
        index 0; earlier versions are 1-based. Getting this wrong shifts every
        reported filename by one.
        """
        header = program.header
        entries = header.get("file_entry") or []
        version = header.get("version", 4)
        names: dict[int, str] = {}
        for index, entry in enumerate(entries):
            raw = entry.name
            name = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            names[index if version >= 5 else index + 1] = name
        return names

    def lookup(self, address: int) -> tuple[str, int] | None:
        """Return the ``(file, line)`` row covering ``address``."""
        if not self._addresses:
            return None
        from bisect import bisect_right

        index = bisect_right(self._addresses, address) - 1
        if index < 0:
            return None
        return self._entries[index]


@lru_cache(maxsize=8)
def _cached_line_table(elf_path: str, mtime: float) -> _DwarfLineTable | None:
    """Cache line tables across requests, keyed by path and mtime.

    Symbolizing a page of crash reports otherwise rebuilds the same table for
    every report. ``mtime`` is part of the key so a replaced artifact is not
    served from a stale cache.
    """
    try:
        return _DwarfLineTable(Path(elf_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("symbolizer.dwarf_cache_failed", error=str(exc))
        return None


def get_line_table(elf_path: Path | str) -> _DwarfLineTable | None:
    """Return a cached DWARF line table for ``elf_path``."""
    path = Path(elf_path)
    if not path.is_file():
        return None
    return _cached_line_table(str(path), path.stat().st_mtime)
