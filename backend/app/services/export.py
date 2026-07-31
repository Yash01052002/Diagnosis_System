"""CSV and PDF export.

CSV is built with the stdlib ``csv`` module — no dependency, and it handles
quoting correctly. The PDF report uses ReportLab, imported lazily so the rest of
the platform (and its tests) does not require it unless a PDF is actually asked
for.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import UTC, datetime

from app.models.crash import CrashReport
from app.schemas.analytics import (
    DashboardSummary,
    DeviceReliabilityReport,
    FirmwareComparison,
)

CRASH_CSV_COLUMNS = [
    "id",
    "occurred_at",
    "received_at",
    "device_id",
    "serial_number",
    "hardware_model",
    "firmware_version",
    "build_version",
    "fault_type",
    "exception_type",
    "task_name",
    "program_counter",
    "top_function",
    "severity",
    "status",
    "crash_signature",
    "group_id",
    "confidence_score",
]


def _hex(value: int | None) -> str:
    return f"0x{value:08X}" if value is not None else ""


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def build_crashes_csv(crashes: Sequence[CrashReport]) -> str:
    """Render crash reports as CSV text, one row per crash."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CRASH_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for c in crashes:
        writer.writerow(
            {
                "id": str(c.id),
                "occurred_at": _iso(c.occurred_at),
                "received_at": _iso(c.received_at),
                "device_id": c.device.device_id if c.device else "",
                "serial_number": c.device.serial_number if c.device else "",
                "hardware_model": c.device.hardware_model if c.device else "",
                "firmware_version": c.firmware_version,
                "build_version": c.build_version or "",
                "fault_type": c.fault_type,
                "exception_type": c.exception_type or "",
                "task_name": c.task_name or "",
                "program_counter": _hex(c.program_counter),
                "top_function": c.top_function or "",
                "severity": c.severity,
                "status": c.status,
                "crash_signature": c.crash_signature or "",
                "group_id": str(c.group_id) if c.group_id else "",
                "confidence_score": (
                    f"{c.confidence_score:.4f}" if c.confidence_score is not None else ""
                ),
            }
        )
    return buffer.getvalue()


def build_analytics_pdf(
    *,
    summary: DashboardSummary,
    firmware: FirmwareComparison,
    reliability: DeviceReliabilityReport,
    generated_by: str,
) -> bytes:
    """Render a one-page analytics report as a PDF (bytes).

    ReportLab is imported here so it is only required when a PDF is requested.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title="BlackBox Analytics Report",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    def table(data: list[list[str]], col_widths: list[float] | None = None) -> Table:
        t = Table(data, colWidths=col_widths, hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f1f5f9")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    story: list = []
    story.append(Paragraph("BlackBox — Crash Diagnosis Analytics", styles["Title"]))
    generated = summary.generated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    story.append(
        Paragraph(
            f"Generated {generated} by {generated_by}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 8 * mm))

    # Headline figures.
    story.append(Paragraph("Overview", styles["Heading2"]))
    overview = [
        ["Metric", "Value"],
        ["Devices (total / active / online)",
         f"{summary.devices.total} / {summary.devices.active} / {summary.devices.online}"],
        ["Device health score", f"{summary.device_health_score}%"],
        ["Crashes (total)", str(summary.crashes.total)],
        ["Crashes today / last 7 days", f"{summary.crashes.today} / {summary.crashes.last_7d}"],
        ["Open / critical open", f"{summary.crashes.open} / {summary.crashes.critical_open}"],
        ["AI diagnoses", str(summary.diagnoses_total)],
        ["Knowledge-base documents", str(summary.documents_total)],
    ]
    story.append(table(overview, [95 * mm, 60 * mm]))
    story.append(Spacer(1, 6 * mm))

    # Fault distribution.
    story.append(Paragraph("Fault distribution", styles["Heading2"]))
    fault_rows = [["Fault type", "Crashes"]]
    fault_rows += [[item.key, str(item.count)] for item in summary.by_fault_type[:12]]
    if len(fault_rows) == 1:
        fault_rows.append(["(none)", "0"])
    story.append(table(fault_rows, [95 * mm, 60 * mm]))
    story.append(Spacer(1, 6 * mm))

    # Top root causes.
    story.append(Paragraph("Top root causes", styles["Heading2"]))
    cause_rows = [["Bug", "Fault", "Severity", "Occurrences", "Devices"]]
    for rc in summary.top_root_causes[:10]:
        cause_rows.append(
            [
                rc.title[:40],
                rc.fault_type,
                rc.severity,
                str(rc.occurrence_count),
                str(rc.device_count),
            ]
        )
    if len(cause_rows) == 1:
        cause_rows.append(["(none)", "", "", "0", "0"])
    story.append(table(cause_rows))
    story.append(Spacer(1, 6 * mm))

    # Firmware comparison.
    story.append(Paragraph("Crashes by firmware", styles["Heading2"]))
    fw_rows = [["Firmware", "Crashes", "Devices"]]
    for fw in firmware.firmwares[:12]:
        fw_rows.append([fw.firmware_version, str(fw.crashes), str(fw.devices)])
    if len(fw_rows) == 1:
        fw_rows.append(["(none)", "0", "0"])
    story.append(table(fw_rows, [80 * mm, 37 * mm, 37 * mm]))
    story.append(Spacer(1, 6 * mm))

    # Reliability.
    story.append(Paragraph("Device reliability (MTBF)", styles["Heading2"]))
    fleet = (
        f"{reliability.fleet_mtbf_hours:.1f} h"
        if reliability.fleet_mtbf_hours is not None
        else "n/a"
    )
    story.append(Paragraph(f"Fleet mean time between failures: {fleet}", styles["Normal"]))
    story.append(Spacer(1, 2 * mm))
    rel_rows = [["Device", "Crashes", "MTBF (h)", "Last crash"]]
    for dev in reliability.devices[:10]:
        rel_rows.append(
            [
                dev.device_identifier,
                str(dev.crashes),
                f"{dev.mtbf_hours:.1f}" if dev.mtbf_hours is not None else "—",
                dev.last_crash_at.strftime("%Y-%m-%d") if dev.last_crash_at else "—",
            ]
        )
    if len(rel_rows) == 1:
        rel_rows.append(["(none)", "0", "—", "—"])
    story.append(table(rel_rows))

    doc.build(story)
    return buffer.getvalue()
