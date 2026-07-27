"""Unit tests for the crash parser.

The parser is the component most exposed to messy real-world input, so these
tests lean on the formats firmware actually emits rather than idealised ones.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.crash import CrashSeverity, FaultType
from app.services.crash_parser import (
    MAX_STACK_WORDS,
    CrashParseError,
    CrashParser,
)

NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def parser() -> CrashParser:
    return CrashParser()


def minimal(**overrides: object) -> dict[str, object]:
    """A payload with just enough to be accepted."""
    payload: dict[str, object] = {
        "device_id": "STM32-F4-0001",
        "firmware_version": "1.4.2",
        "fault_type": "HardFault",
    }
    payload.update(overrides)
    return payload


class TestRequiredFields:
    def test_minimal_payload_parses(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(), now=NOW)

        assert parsed.firmware_version == "1.4.2"
        assert parsed.fault_type is FaultType.HARD_FAULT
        assert parsed.device_identifier == "STM32-F4-0001"

    def test_missing_firmware_version_is_rejected(self, parser: CrashParser) -> None:
        with pytest.raises(CrashParseError, match="firmware_version"):
            parser.parse({"device_id": "x", "fault_type": "HardFault"}, now=NOW)

    def test_non_object_payload_is_rejected(self, parser: CrashParser) -> None:
        with pytest.raises(CrashParseError, match="JSON object"):
            parser.parse("not a dict", now=NOW)  # type: ignore[arg-type]

    def test_missing_fault_type_becomes_unknown(self, parser: CrashParser) -> None:
        parsed = parser.parse({"device_id": "x", "firmware_version": "1.0.0"}, now=NOW)

        assert parsed.fault_type is FaultType.UNKNOWN
        assert any("fault_type" in warning for warning in parsed.warnings)


class TestFieldAliases:
    @pytest.mark.parametrize(
        "alias", ["firmware_version", "firmwareVersion", "fw_version", "fw", "version"]
    )
    def test_firmware_aliases(self, parser: CrashParser, alias: str) -> None:
        parsed = parser.parse({alias: "2.0.0", "fault_type": "HardFault"}, now=NOW)

        assert parsed.firmware_version == "2.0.0"

    @pytest.mark.parametrize("alias", ["program_counter", "programCounter", "pc", "PC"])
    def test_program_counter_aliases(self, parser: CrashParser, alias: str) -> None:
        parsed = parser.parse(minimal(**{alias: "0x08001A2C"}), now=NOW)

        assert parsed.program_counter == 0x08001A2C

    @pytest.mark.parametrize("alias", ["task_name", "taskName", "task", "thread"])
    def test_task_aliases(self, parser: CrashParser, alias: str) -> None:
        parsed = parser.parse(minimal(**{alias: "SensorTask"}), now=NOW)

        assert parsed.task_name == "SensorTask"

    def test_first_alias_wins(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(program_counter="0x08000000", pc="0x08FFFFFF"), now=NOW)

        assert parsed.program_counter == 0x08000000


class TestAddressParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("0x08001A2C", 0x08001A2C),
            ("0X08001A2C", 0x08001A2C),
            ("08001A2C", 0x08001A2C),
            ("0x0800_1A2C", 0x08001A2C),
            ("  0x08001A2C  ", 0x08001A2C),
            (0x08001A2C, 0x08001A2C),
            (0, 0),
            (0xFFFFFFFF, 0xFFFFFFFF),
        ],
    )
    def test_accepted_formats(self, value: object, expected: int) -> None:
        assert CrashParser.parse_address(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "   ",
            "not-hex",
            "0xZZZZ",
            -1,
            0x1_0000_0000,  # beyond 32 bits
            True,  # bool is an int subclass; not an address
            [1, 2],
            {"a": 1},
        ],
    )
    def test_rejected_values(self, value: object) -> None:
        assert CrashParser.parse_address(value) is None

    def test_unparsable_address_warns_but_does_not_fail(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(pc="garbage"), now=NOW)

        assert parsed.program_counter is None
        assert any("program_counter" in warning for warning in parsed.warnings)


class TestTimestamps:
    def test_iso_with_zulu(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp="2026-07-27T09:14:22Z"), now=NOW)

        assert parsed.occurred_at == datetime(2026, 7, 27, 9, 14, 22, tzinfo=UTC)

    def test_iso_with_offset_is_converted_to_utc(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp="2026-07-27T11:14:22+02:00"), now=NOW)

        assert parsed.occurred_at == datetime(2026, 7, 27, 9, 14, 22, tzinfo=UTC)

    def test_naive_iso_is_treated_as_utc(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp="2026-07-27T09:14:22"), now=NOW)

        assert parsed.occurred_at.tzinfo is not None
        assert parsed.occurred_at.hour == 9

    def test_epoch_seconds(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp=1769509422), now=NOW)

        assert parsed.occurred_at == datetime.fromtimestamp(1769509422, tz=UTC)

    def test_epoch_milliseconds(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp=1769509422000), now=NOW)

        assert parsed.occurred_at == datetime.fromtimestamp(1769509422, tz=UTC)

    def test_epoch_as_string(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp="1769509422"), now=NOW)

        assert parsed.occurred_at == datetime.fromtimestamp(1769509422, tz=UTC)

    def test_missing_timestamp_defaults_to_receipt(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(), now=NOW)

        assert parsed.occurred_at == NOW
        assert any("timestamp" in warning for warning in parsed.warnings)

    def test_unparsable_timestamp_falls_back(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(timestamp="last tuesday"), now=NOW)

        assert parsed.occurred_at == NOW
        assert any("timestamp" in warning for warning in parsed.warnings)

    def test_slightly_future_timestamp_warns(self, parser: CrashParser) -> None:
        future = (NOW + timedelta(minutes=5)).isoformat()

        parsed = parser.parse(minimal(timestamp=future), now=NOW)

        assert any("future" in warning for warning in parsed.warnings)

    def test_wildly_future_timestamp_is_rejected(self, parser: CrashParser) -> None:
        future = (NOW + timedelta(days=400)).isoformat()

        with pytest.raises(CrashParseError, match="device clock"):
            parser.parse(minimal(timestamp=future), now=NOW)


class TestFaultClassification:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("HardFault", FaultType.HARD_FAULT),
            ("hard_fault", FaultType.HARD_FAULT),
            ("HARDFAULT", FaultType.HARD_FAULT),
            ("Hard Fault", FaultType.HARD_FAULT),
            ("BusFault", FaultType.BUS_FAULT),
            ("bus fault detected", FaultType.BUS_FAULT),
            ("MemManage", FaultType.MEM_MANAGE_FAULT),
            ("MPU violation", FaultType.MEM_MANAGE_FAULT),
            ("UsageFault", FaultType.USAGE_FAULT),
            ("stack overflow", FaultType.STACK_OVERFLOW),
            ("StackOverflow in task", FaultType.STACK_OVERFLOW),
            ("watchdog reset", FaultType.WATCHDOG_RESET),
            ("IWDG", FaultType.WATCHDOG_RESET),
            ("configASSERT failed", FaultType.ASSERTION_FAILED),
            ("malloc failed", FaultType.MALLOC_FAILED),
            ("heap exhausted", FaultType.MALLOC_FAILED),
            ("kernel panic", FaultType.PANIC),
            ("something else entirely", FaultType.UNKNOWN),
            ("", FaultType.UNKNOWN),
        ],
    )
    def test_classification(self, raw: str, expected: FaultType) -> None:
        assert CrashParser.classify_fault(raw) is expected

    def test_stack_overflow_beats_generic_fault(self) -> None:
        """A more specific pattern must not be shadowed by a broader one."""
        assert (
            CrashParser.classify_fault("HardFault from stack overflow") is FaultType.STACK_OVERFLOW
        )

    def test_falls_back_to_exception_field(self, parser: CrashParser) -> None:
        payload = {
            "device_id": "x",
            "firmware_version": "1.0.0",
            "exception_type": "BusFault",
        }

        parsed = parser.parse(payload, now=NOW)

        assert parsed.fault_type is FaultType.BUS_FAULT

    def test_unrecognised_fault_warns(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(fault_type="quantum anomaly"), now=NOW)

        assert parsed.fault_type is FaultType.UNKNOWN
        assert any("unrecognised" in warning for warning in parsed.warnings)


class TestSeverity:
    @pytest.mark.parametrize(
        ("fault", "expected"),
        [
            (FaultType.HARD_FAULT, CrashSeverity.CRITICAL),
            (FaultType.MEM_MANAGE_FAULT, CrashSeverity.CRITICAL),
            (FaultType.STACK_OVERFLOW, CrashSeverity.CRITICAL),
            (FaultType.BUS_FAULT, CrashSeverity.HIGH),
            (FaultType.WATCHDOG_RESET, CrashSeverity.HIGH),
            (FaultType.ASSERTION_FAILED, CrashSeverity.MEDIUM),
            (FaultType.UNKNOWN, CrashSeverity.MEDIUM),
        ],
    )
    def test_derived_from_fault(self, fault: FaultType, expected: CrashSeverity) -> None:
        assert CrashParser.derive_severity(fault) is expected

    def test_explicit_severity_wins(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(fault_type="HardFault", severity="low"), now=NOW)

        assert parsed.severity is CrashSeverity.LOW

    @pytest.mark.parametrize(
        ("alias", "expected"),
        [
            ("fatal", CrashSeverity.CRITICAL),
            ("error", CrashSeverity.HIGH),
            ("warning", CrashSeverity.MEDIUM),
            ("info", CrashSeverity.LOW),
        ],
    )
    def test_log_level_aliases(
        self, parser: CrashParser, alias: str, expected: CrashSeverity
    ) -> None:
        parsed = parser.parse(minimal(severity=alias), now=NOW)

        assert parsed.severity is expected

    def test_unknown_severity_falls_back_to_derived(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(fault_type="BusFault", severity="spicy"), now=NOW)

        assert parsed.severity is CrashSeverity.HIGH
        assert any("severity" in warning for warning in parsed.warnings)


class TestRegisterDump:
    def test_mapping_is_normalised(self, parser: CrashParser) -> None:
        payload = minimal(
            register_dump={"R0": "0x00000000", "r1": "0x20000100", "XPSR": "0x61000000"}
        )

        parsed = parser.parse(payload, now=NOW)

        assert parsed.register_dump == {"r0": 0, "r1": 0x20000100, "psr": 0x61000000}

    def test_list_is_positional(self, parser: CrashParser) -> None:
        payload = minimal(register_dump=["0x1", "0x2", "0x3"])

        parsed = parser.parse(payload, now=NOW)

        assert parsed.register_dump == {"r0": 1, "r1": 2, "r2": 3}

    def test_registers_are_sorted_numerically(self, parser: CrashParser) -> None:
        payload = minimal(register_dump={"r10": 10, "r2": 2, "r1": 1, "lr": 99})

        parsed = parser.parse(payload, now=NOW)

        assert list(parsed.register_dump or {}) == ["r1", "r2", "r10", "lr"]

    def test_unknown_register_names_are_dropped_with_a_warning(self, parser: CrashParser) -> None:
        payload = minimal(register_dump={"r0": 1, "banana": 2, "r99": 3})

        parsed = parser.parse(payload, now=NOW)

        assert parsed.register_dump == {"r0": 1}
        assert any("registers" in warning for warning in parsed.warnings)

    def test_pc_lr_sp_backfilled_from_dump(self, parser: CrashParser) -> None:
        """Handlers often dump the register file without repeating PC/LR/SP."""
        payload = minimal(
            register_dump={"pc": "0x08001A2C", "lr": "0x08001A0F", "sp": "0x20017FA0"}
        )

        parsed = parser.parse(payload, now=NOW)

        assert parsed.program_counter == 0x08001A2C
        assert parsed.link_register == 0x08001A0F
        assert parsed.stack_pointer == 0x20017FA0
        assert any("register dump" in warning for warning in parsed.warnings)

    def test_explicit_fields_are_not_overwritten(self, parser: CrashParser) -> None:
        payload = minimal(pc="0x08000000", register_dump={"pc": "0x08FFFFFF"})

        parsed = parser.parse(payload, now=NOW)

        assert parsed.program_counter == 0x08000000

    def test_non_collection_is_rejected_with_a_warning(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(register_dump="r0=1"), now=NOW)

        assert parsed.register_dump is None
        assert any("registers" in warning for warning in parsed.warnings)


class TestStackDump:
    def test_list_of_hex_strings(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(stack_dump=["0x08001A2C", "0x20017FB0"]), now=NOW)

        assert parsed.stack_dump == {
            "start_address": None,
            "words": [0x08001A2C, 0x20017FB0],
        }

    @pytest.mark.parametrize(
        "blob",
        [
            "0x08001A2C 0x20017FB0",
            "0x08001A2C,0x20017FB0",
            "0x08001A2C; 0x20017FB0",
            "0x08001A2C\n0x20017FB0",
        ],
    )
    def test_delimited_string(self, parser: CrashParser, blob: str) -> None:
        parsed = parser.parse(minimal(stack_dump=blob), now=NOW)

        assert (parsed.stack_dump or {})["words"] == [0x08001A2C, 0x20017FB0]

    def test_object_with_start_address(self, parser: CrashParser) -> None:
        payload = minimal(stack_dump={"start_address": "0x20017F00", "words": ["0x1", "0x2"]})

        parsed = parser.parse(payload, now=NOW)

        assert parsed.stack_dump == {"start_address": 0x20017F00, "words": [1, 2]}

    def test_unreadable_words_are_skipped(self, parser: CrashParser) -> None:
        parsed = parser.parse(minimal(stack_dump=["0x1", "junk", "0x3"]), now=NOW)

        assert (parsed.stack_dump or {})["words"] == [1, 3]
        assert any("unreadable" in warning for warning in parsed.warnings)

    def test_oversized_dump_is_truncated(self, parser: CrashParser) -> None:
        words = ["0x1"] * (MAX_STACK_WORDS + 50)

        parsed = parser.parse(minimal(stack_dump=words), now=NOW)

        assert len((parsed.stack_dump or {})["words"]) == MAX_STACK_WORDS
        assert any("truncated" in warning for warning in parsed.warnings)

    def test_empty_dump_is_none(self, parser: CrashParser) -> None:
        assert parser.parse(minimal(stack_dump=[]), now=NOW).stack_dump is None


class TestRealisticPayloads:
    def test_stm32_freertos_hardfault(self, parser: CrashParser) -> None:
        """The shape a typical Cortex-M fault handler emits."""
        payload = {
            "device_id": "STM32-F4-0001",
            "firmware_version": "1.4.2",
            "build_version": "a1b2c3d",
            "timestamp": "2026-07-27T09:14:22Z",
            "fault_type": "HardFault",
            "exception_type": "IMPRECISERR",
            "task_name": "SensorTask",
            "pc": "0x08001A2C",
            "lr": "0x08001A0F",
            "sp": "0x20017FA0",
            "registers": {
                "r0": "0x00000000",
                "r1": "0x20000100",
                "r2": "0xDEADBEEF",
                "r3": "0x00000001",
                "r12": "0x00000000",
                "xpsr": "0x61000000",
                "cfsr": "0x00000400",
                "hfsr": "0x40000000",
            },
            "stack": ["0x0800 1A2C", "0x20017FB0", "0x08001998"],
        }

        parsed = parser.parse(payload, now=NOW)

        assert parsed.fault_type is FaultType.HARD_FAULT
        assert parsed.severity is CrashSeverity.CRITICAL
        assert parsed.task_name == "SensorTask"
        assert parsed.program_counter == 0x08001A2C
        assert (parsed.register_dump or {})["r2"] == 0xDEADBEEF
        assert (parsed.register_dump or {})["cfsr"] == 0x0400
        assert parsed.build_version == "a1b2c3d"

    def test_camel_case_payload(self, parser: CrashParser) -> None:
        """A JSON-from-C++ build that camel-cases everything."""
        payload = {
            "deviceId": "STM32-F4-0002",
            "firmwareVersion": "2.0.0",
            "faultType": "busFault",
            "taskName": "CommsTask",
            "programCounter": 134225964,
            "stackDump": "08001A2C 20017FB0",
        }

        parsed = parser.parse(payload, now=NOW)

        assert parsed.device_identifier == "STM32-F4-0002"
        assert parsed.fault_type is FaultType.BUS_FAULT
        assert parsed.program_counter == 134225964
        assert (parsed.stack_dump or {})["words"] == [0x08001A2C, 0x20017FB0]

    def test_minimal_watchdog_report(self, parser: CrashParser) -> None:
        """A watchdog reset carries no registers at all — still a real crash."""
        payload = {"device": "STM32-F4-0003", "fw": "1.0.0", "reason": "IWDG timeout"}

        parsed = parser.parse(payload, now=NOW)

        assert parsed.fault_type is FaultType.WATCHDOG_RESET
        assert parsed.severity is CrashSeverity.HIGH
        assert parsed.program_counter is None

    def test_warnings_do_not_prevent_parsing(self, parser: CrashParser) -> None:
        """Every field is malformed, yet the report is still salvaged."""
        payload = {
            "firmware_version": "1.0.0",
            "fault_type": "???",
            "timestamp": "whenever",
            "pc": "nonsense",
            "registers": "not-an-object",
            "stack": ["bad", "worse"],
        }

        parsed = parser.parse(payload, now=NOW)

        assert parsed.fault_type is FaultType.UNKNOWN
        assert parsed.occurred_at == NOW
        assert len(parsed.warnings) >= 4
