"""Crash log parsing and normalization.

Firmware in the field is not uniform. Different builds spell the same field
half a dozen ways (``pc``, ``PC``, ``program_counter``), send addresses as
hex strings or integers, and timestamps as ISO-8601 or epoch seconds. This
module turns any of that into one canonical shape.

Two principles govern the design:

1. **Be liberal in what is accepted, strict in what is stored.** A report that
   arrives in an odd format is normalised and a warning is recorded; only a
   report that is genuinely unusable is rejected. Crashes are evidence — the
   ones hardest to parse are often the ones most worth keeping.
2. **Never lose the original.** The raw payload is stored alongside the parsed
   result so a report can be re-parsed when the parser improves or when
   symbolization arrives (Phase 2.5).

The module is pure: no database, no network, no framework. That keeps the
rules exhaustively testable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import ValidationError
from app.models.crash import CrashSeverity, FaultType

#: Bumped when normalisation changes in a way that would alter stored output.
#: Persisted per report so re-parsing can be targeted at stale rows.
PARSER_VERSION = "1.0"

#: 32-bit address space of a Cortex-M part.
MAX_ADDRESS = 0xFFFFFFFF

#: Guards against a runaway device flooding the database with one report.
MAX_STACK_WORDS = 4096
MAX_REGISTERS = 64

#: Reports dated further ahead than this are rejected: a device whose clock is
#: wrong by more than a day would otherwise poison every time-based chart.
MAX_CLOCK_SKEW = timedelta(days=1)

#: Accepted spellings for each canonical field. Order matters: the first key
#: present in the payload wins.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "device_identifier": ("device_id", "deviceId", "device", "serial_number", "serial", "uid"),
    "firmware_version": ("firmware_version", "firmwareVersion", "fw_version", "fw", "version"),
    "build_version": ("build_version", "buildVersion", "build", "build_id", "git_sha", "commit"),
    "occurred_at": ("timestamp", "occurred_at", "occurredAt", "time", "ts", "crash_time"),
    "fault_type": ("fault_type", "faultType", "fault", "type", "reason", "crash_type"),
    "exception_type": ("exception_type", "exceptionType", "exception", "exc"),
    "task_name": ("task_name", "taskName", "task", "thread", "thread_name"),
    "program_counter": ("program_counter", "programCounter", "pc", "PC"),
    "link_register": ("link_register", "linkRegister", "lr", "LR"),
    "stack_pointer": ("stack_pointer", "stackPointer", "sp", "SP", "msp", "MSP"),
    "registers": ("register_dump", "registerDump", "registers", "regs", "core_registers"),
    "stack": ("stack_dump", "stackDump", "stack", "stack_trace", "stack_words"),
    "severity": ("severity", "level", "priority"),
    "notes": ("notes", "note", "message", "detail", "description"),
}

#: Substring patterns mapped to a fault type, checked in order. Longer, more
#: specific patterns must come first ("stack overflow" before "overflow").
_FAULT_PATTERNS: tuple[tuple[str, FaultType], ...] = (
    ("stackoverflow", FaultType.STACK_OVERFLOW),
    ("stack_overflow", FaultType.STACK_OVERFLOW),
    ("stackovf", FaultType.STACK_OVERFLOW),
    ("memmanage", FaultType.MEM_MANAGE_FAULT),
    ("memfault", FaultType.MEM_MANAGE_FAULT),
    ("mpu", FaultType.MEM_MANAGE_FAULT),
    ("busfault", FaultType.BUS_FAULT),
    ("buserror", FaultType.BUS_FAULT),
    ("usagefault", FaultType.USAGE_FAULT),
    ("hardfault", FaultType.HARD_FAULT),
    ("watchdog", FaultType.WATCHDOG_RESET),
    ("wdt", FaultType.WATCHDOG_RESET),
    ("iwdg", FaultType.WATCHDOG_RESET),
    ("assert", FaultType.ASSERTION_FAILED),
    ("malloc", FaultType.MALLOC_FAILED),
    ("outofmemory", FaultType.MALLOC_FAILED),
    ("oom", FaultType.MALLOC_FAILED),
    ("heap", FaultType.MALLOC_FAILED),
    ("panic", FaultType.PANIC),
    ("abort", FaultType.PANIC),
)

#: Baseline severity per fault type. A fault that corrupts memory or resets the
#: part is worse than one the firmware caught deliberately.
_SEVERITY_BY_FAULT: dict[FaultType, CrashSeverity] = {
    FaultType.HARD_FAULT: CrashSeverity.CRITICAL,
    FaultType.MEM_MANAGE_FAULT: CrashSeverity.CRITICAL,
    FaultType.STACK_OVERFLOW: CrashSeverity.CRITICAL,
    FaultType.BUS_FAULT: CrashSeverity.HIGH,
    FaultType.USAGE_FAULT: CrashSeverity.HIGH,
    FaultType.MALLOC_FAILED: CrashSeverity.HIGH,
    FaultType.WATCHDOG_RESET: CrashSeverity.HIGH,
    FaultType.PANIC: CrashSeverity.HIGH,
    FaultType.ASSERTION_FAILED: CrashSeverity.MEDIUM,
    FaultType.UNKNOWN: CrashSeverity.MEDIUM,
}

#: Canonical register names. ``xpsr`` and ``psr`` are the same register.
_REGISTER_ALIASES: dict[str, str] = {
    "xpsr": "psr",
    "apsr": "psr",
    "ipsr": "psr",
    "epsr": "psr",
    "fp": "r11",
    "ip": "r12",
    "sl": "r10",
}

_REGISTER_NAME = re.compile(
    r"^(r\d{1,2}|sp|lr|pc|psr|msp|psp|primask|basepri|control|"
    r"cfsr|hfsr|mmfar|bfar|dfsr|afsr|shcsr)$"
)

_HEX = re.compile(r"^(?:0x|0X)?([0-9a-fA-F_]+)$")
_SPLIT = re.compile(r"[\s,;]+")


class CrashParseError(ValidationError):
    """Raised when a payload cannot be turned into a storable crash report."""

    error_code = "crash_parse_error"
    message = "The crash report could not be parsed."


@dataclass(slots=True)
class ParsedCrash:
    """Normalised crash data, ready to persist."""

    device_identifier: str | None
    firmware_version: str
    occurred_at: datetime
    fault_type: FaultType
    severity: CrashSeverity
    build_version: str | None = None
    exception_type: str | None = None
    task_name: str | None = None
    program_counter: int | None = None
    link_register: int | None = None
    stack_pointer: int | None = None
    register_dump: dict[str, int] | None = None
    stack_dump: dict[str, Any] | None = None
    notes: str | None = None
    warnings: list[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION


class CrashParser:
    """Turns a raw device payload into a :class:`ParsedCrash`.

    Stateless — a single instance is safe to share.
    """

    def parse(self, payload: Mapping[str, Any], *, now: datetime | None = None) -> ParsedCrash:
        """Normalise ``payload``.

        Args:
            payload: The raw JSON object submitted by the device.
            now: Reference time for clock-skew checks. Injected by tests.

        Raises:
            CrashParseError: if a required field is missing or unusable.
        """
        if not isinstance(payload, Mapping):
            raise CrashParseError("Crash payload must be a JSON object.")

        reference = now or datetime.now(UTC)
        warnings: list[str] = []

        firmware_version = self._require_text(payload, "firmware_version", max_length=50)
        occurred_at = self._parse_timestamp(
            self._lookup(payload, "occurred_at"), reference, warnings
        )
        fault_type = self._parse_fault_type(payload, warnings)

        parsed = ParsedCrash(
            device_identifier=self._optional_text(payload, "device_identifier", max_length=64),
            firmware_version=firmware_version,
            occurred_at=occurred_at,
            fault_type=fault_type,
            severity=self._resolve_severity(payload, fault_type, warnings),
            build_version=self._optional_text(payload, "build_version", max_length=100),
            exception_type=self._optional_text(payload, "exception_type", max_length=100),
            task_name=self._optional_text(payload, "task_name", max_length=100),
            notes=self._optional_text(payload, "notes", max_length=5000),
            warnings=warnings,
        )

        parsed.program_counter = self._parse_address_field(payload, "program_counter", warnings)
        parsed.link_register = self._parse_address_field(payload, "link_register", warnings)
        parsed.stack_pointer = self._parse_address_field(payload, "stack_pointer", warnings)
        parsed.register_dump = self._parse_registers(self._lookup(payload, "registers"), warnings)
        parsed.stack_dump = self._parse_stack(self._lookup(payload, "stack"), warnings)

        self._backfill_from_registers(parsed, warnings)
        return parsed

    # ------------------------------------------------------------------
    # Field lookup
    # ------------------------------------------------------------------
    @staticmethod
    def _lookup(payload: Mapping[str, Any], canonical: str) -> Any:
        """Return the first aliased value present, or ``None``."""
        for alias in FIELD_ALIASES[canonical]:
            if alias in payload and payload[alias] is not None:
                return payload[alias]
        return None

    def _require_text(self, payload: Mapping[str, Any], canonical: str, *, max_length: int) -> str:
        value = self._optional_text(payload, canonical, max_length=max_length)
        if not value:
            raise CrashParseError(
                f"Field '{canonical}' is required.",
                details={"field": canonical, "accepted_names": list(FIELD_ALIASES[canonical])},
            )
        return value

    def _optional_text(
        self, payload: Mapping[str, Any], canonical: str, *, max_length: int
    ) -> str | None:
        value = self._lookup(payload, canonical)
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text[:max_length]

    # ------------------------------------------------------------------
    # Addresses
    # ------------------------------------------------------------------
    def _parse_address_field(
        self, payload: Mapping[str, Any], canonical: str, warnings: list[str]
    ) -> int | None:
        raw = self._lookup(payload, canonical)
        if raw is None:
            return None
        address = self.parse_address(raw)
        if address is None:
            warnings.append(f"{canonical}: could not interpret {raw!r} as an address")
        return address

    @staticmethod
    def parse_address(value: Any) -> int | None:
        """Coerce ``value`` to a 32-bit address.

        Accepts ``0x0800ABCD``, ``0800ABCD``, ``0x0800_ABCD`` and plain
        integers. Returns ``None`` when the value is not a usable address —
        including negatives, which are almost always a signedness bug on the
        device rather than a real address.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if 0 <= value <= MAX_ADDRESS else None
        if isinstance(value, float):
            return int(value) if value.is_integer() and 0 <= value <= MAX_ADDRESS else None
        if not isinstance(value, str):
            return None

        text = value.strip()
        if not text:
            return None

        match = _HEX.match(text)
        if match:
            digits = match.group(1).replace("_", "")
            # A bare decimal-looking string with no 0x prefix is ambiguous.
            # Devices overwhelmingly send hex, so hex wins; the value is still
            # range-checked below.
            try:
                parsed = int(digits, 16)
            except ValueError:
                return None
            return parsed if 0 <= parsed <= MAX_ADDRESS else None
        return None

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    def _parse_timestamp(self, value: Any, reference: datetime, warnings: list[str]) -> datetime:
        """Interpret a device timestamp, defaulting to now when absent.

        Accepts ISO-8601 (with or without a zone) and epoch seconds or
        milliseconds. Naive values are treated as UTC, because a device that
        omits a zone is not reporting local time in any usable sense.
        """
        if value is None:
            warnings.append("timestamp: missing, using time of receipt")
            return reference

        parsed: datetime | None = None

        if isinstance(value, bool):
            parsed = None
        elif isinstance(value, int | float):
            parsed = self._from_epoch(float(value))
        elif isinstance(value, str):
            text = value.strip()
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                try:
                    parsed = self._from_epoch(float(text))
                except ValueError:
                    parsed = None

        if parsed is None:
            warnings.append(f"timestamp: could not interpret {value!r}, using time of receipt")
            return reference

        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

        if parsed > reference + MAX_CLOCK_SKEW:
            raise CrashParseError(
                "Crash timestamp is too far in the future; check the device clock.",
                details={"timestamp": parsed.isoformat(), "server_time": reference.isoformat()},
            )
        if parsed > reference:
            warnings.append("timestamp: slightly in the future, device clock may be skewed")
        return parsed

    @staticmethod
    def _from_epoch(value: float) -> datetime | None:
        """Interpret an epoch value, guessing seconds vs milliseconds.

        Anything past year 2286 in seconds is far more likely to be
        milliseconds, which is how most RTOS ticks are reported.
        """
        if value <= 0:
            return None
        if value > 1e11:
            value /= 1000.0
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Fault type and severity
    # ------------------------------------------------------------------
    def _parse_fault_type(self, payload: Mapping[str, Any], warnings: list[str]) -> FaultType:
        raw = self._lookup(payload, "fault_type")
        if raw is None:
            # The exception field often carries the classification instead.
            raw = self._lookup(payload, "exception_type")
        if raw is None:
            warnings.append("fault_type: missing, classified as unknown")
            return FaultType.UNKNOWN

        fault_type = self.classify_fault(str(raw))
        if fault_type is FaultType.UNKNOWN:
            warnings.append(f"fault_type: unrecognised value {str(raw)[:60]!r}")
        return fault_type

    @staticmethod
    def classify_fault(value: str) -> FaultType:
        """Map a free-form fault description onto a :class:`FaultType`."""
        squashed = re.sub(r"[^a-z0-9]", "", value.lower())
        if not squashed:
            return FaultType.UNKNOWN

        # An exact canonical value should not be re-derived from substrings.
        for member in FaultType:
            if squashed == member.value.replace("_", ""):
                return member

        for pattern, fault_type in _FAULT_PATTERNS:
            if pattern in squashed:
                return fault_type
        return FaultType.UNKNOWN

    def _resolve_severity(
        self, payload: Mapping[str, Any], fault_type: FaultType, warnings: list[str]
    ) -> CrashSeverity:
        """Honour a device-supplied severity, else derive one from the fault."""
        raw = self._lookup(payload, "severity")
        if raw is not None:
            text = str(raw).strip().lower()
            for member in CrashSeverity:
                if text == member.value:
                    return member
            aliases = {
                "info": CrashSeverity.LOW,
                "debug": CrashSeverity.LOW,
                "warn": CrashSeverity.MEDIUM,
                "warning": CrashSeverity.MEDIUM,
                "error": CrashSeverity.HIGH,
                "err": CrashSeverity.HIGH,
                "fatal": CrashSeverity.CRITICAL,
                "emergency": CrashSeverity.CRITICAL,
            }
            if text in aliases:
                return aliases[text]
            warnings.append(f"severity: unrecognised value {text[:30]!r}, derived from fault type")
        return self.derive_severity(fault_type)

    @staticmethod
    def derive_severity(fault_type: FaultType) -> CrashSeverity:
        """Baseline severity for a fault type."""
        return _SEVERITY_BY_FAULT.get(fault_type, CrashSeverity.MEDIUM)

    # ------------------------------------------------------------------
    # Register and stack dumps
    # ------------------------------------------------------------------
    def _parse_registers(self, value: Any, warnings: list[str]) -> dict[str, int] | None:
        """Normalise a register dump to ``{"r0": int, ...}``.

        Accepts a mapping of names to values, or a positional list which is
        interpreted as r0, r1, r2 ... following the AAPCS dump order used by
        most fault handlers.
        """
        if value is None:
            return None

        pairs: list[tuple[str, Any]]
        if isinstance(value, Mapping):
            pairs = list(value.items())
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            pairs = [(f"r{index}", item) for index, item in enumerate(value)]
            if len(pairs) > MAX_REGISTERS:
                warnings.append(f"registers: {len(pairs)} entries truncated to {MAX_REGISTERS}")
                pairs = pairs[:MAX_REGISTERS]
        else:
            warnings.append(f"registers: expected an object or array, got {type(value).__name__}")
            return None

        registers: dict[str, int] = {}
        skipped: list[str] = []
        for name, raw in pairs:
            canonical = self._canonical_register(str(name))
            if canonical is None:
                skipped.append(str(name)[:20])
                continue
            address = self.parse_address(raw)
            if address is None:
                skipped.append(str(name)[:20])
                continue
            registers[canonical] = address

        if skipped:
            warnings.append("registers: ignored unusable entries " + ", ".join(sorted(skipped)[:8]))
        if not registers:
            return None
        # Sort r0..r12 numerically, then named registers alphabetically, so the
        # stored JSON reads like a debugger dump rather than in insertion order.
        return dict(sorted(registers.items(), key=self._register_sort_key))

    @staticmethod
    def _canonical_register(name: str) -> str | None:
        cleaned = re.sub(r"[^a-z0-9]", "", name.lower())
        cleaned = _REGISTER_ALIASES.get(cleaned, cleaned)
        if not _REGISTER_NAME.match(cleaned):
            return None
        if cleaned.startswith("r") and cleaned[1:].isdigit() and int(cleaned[1:]) > 15:
            return None
        return cleaned

    @staticmethod
    def _register_sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
        name = item[0]
        if name.startswith("r") and name[1:].isdigit():
            return (0, int(name[1:]), "")
        return (1, 0, name)

    def _parse_stack(self, value: Any, warnings: list[str]) -> dict[str, Any] | None:
        """Normalise a stack dump to ``{"start_address": int|None, "words": [...]}``.

        Accepts a list of words, a whitespace/comma separated string, or an
        object carrying both the words and the address they start at.
        """
        if value is None:
            return None

        start_address: int | None = None
        raw_words: Any = value

        if isinstance(value, Mapping):
            for key in ("start_address", "startAddress", "address", "base", "sp"):
                if key in value:
                    start_address = self.parse_address(value[key])
                    break
            raw_words = None
            for key in ("words", "data", "stack", "values", "dump"):
                if key in value:
                    raw_words = value[key]
                    break
            if raw_words is None:
                warnings.append("stack: object contained no recognisable word list")
                return None

        if isinstance(raw_words, str):
            tokens: Iterable[Any] = [tok for tok in _SPLIT.split(raw_words.strip()) if tok]
        elif isinstance(raw_words, Sequence) and not isinstance(raw_words, bytes):
            tokens = raw_words
        else:
            warnings.append(f"stack: expected an array or string, got {type(raw_words).__name__}")
            return None

        tokens = list(tokens)
        if len(tokens) > MAX_STACK_WORDS:
            warnings.append(f"stack: {len(tokens)} words truncated to {MAX_STACK_WORDS}")
            tokens = tokens[:MAX_STACK_WORDS]

        words: list[int] = []
        unusable = 0
        for token in tokens:
            address = self.parse_address(token)
            if address is None:
                unusable += 1
                continue
            words.append(address)

        if unusable:
            warnings.append(f"stack: skipped {unusable} unreadable word(s)")
        if not words:
            return None
        return {"start_address": start_address, "words": words}

    # ------------------------------------------------------------------
    # Cross-field completion
    # ------------------------------------------------------------------
    @staticmethod
    def _backfill_from_registers(parsed: ParsedCrash, warnings: list[str]) -> None:
        """Fill missing PC/LR/SP from the register dump.

        Many fault handlers dump the full register file and do not repeat the
        three key registers as separate fields.
        """
        if not parsed.register_dump:
            return
        for attribute, register in (
            ("program_counter", "pc"),
            ("link_register", "lr"),
            ("stack_pointer", "sp"),
        ):
            if getattr(parsed, attribute) is None and register in parsed.register_dump:
                setattr(parsed, attribute, parsed.register_dump[register])
                warnings.append(f"{attribute}: taken from the register dump")


#: Shared instance — the parser holds no state.
crash_parser = CrashParser()
