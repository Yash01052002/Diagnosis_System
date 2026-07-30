// Enum → display label and badge tone mappings, in one place so a status colour
// is consistent everywhere it appears.
import type {
  ConfidenceLabel,
  CrashGroupStatus,
  CrashSeverity,
  CrashStatus,
  DeviceStatus,
  DocumentSourceType,
  DocumentStatus,
} from "../api/types";

export type Tone =
  | "neutral"
  | "brand"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "purple";

export const severityTone: Record<CrashSeverity, Tone> = {
  low: "neutral",
  medium: "info",
  high: "warning",
  critical: "danger",
};

export const crashStatusTone: Record<CrashStatus, Tone> = {
  new: "brand",
  triaged: "info",
  investigating: "warning",
  resolved: "success",
  ignored: "neutral",
  duplicate: "neutral",
};

export const deviceStatusTone: Record<DeviceStatus, Tone> = {
  active: "success",
  inactive: "neutral",
  maintenance: "warning",
  decommissioned: "danger",
};

export const groupStatusTone: Record<CrashGroupStatus, Tone> = {
  open: "brand",
  investigating: "warning",
  resolved: "success",
  ignored: "neutral",
  regressed: "danger",
};

export const documentStatusTone: Record<DocumentStatus, Tone> = {
  pending: "neutral",
  processing: "info",
  indexed: "success",
  failed: "danger",
};

export const confidenceTone: Record<ConfidenceLabel, Tone> = {
  certain: "success",
  likely: "info",
  uncertain: "warning",
};

export const sourceTypeLabel: Record<DocumentSourceType, string> = {
  stm32_reference: "STM32 Reference",
  freertos_doc: "FreeRTOS Doc",
  arm_cortex_m: "ARM Cortex-M",
  engineering_note: "Engineering Note",
  troubleshooting: "Troubleshooting",
  application_note: "Application Note",
  previous_crash: "Previous Crash",
  other: "Other",
};

export const FAULT_TYPES = [
  "hard_fault",
  "bus_fault",
  "mem_manage_fault",
  "usage_fault",
  "stack_overflow",
  "watchdog_reset",
  "assertion_failed",
  "malloc_failed",
  "panic",
  "unknown",
] as const;

export const CRASH_STATUSES: CrashStatus[] = [
  "new",
  "triaged",
  "investigating",
  "resolved",
  "ignored",
  "duplicate",
];

export const CRASH_SEVERITIES: CrashSeverity[] = [
  "low",
  "medium",
  "high",
  "critical",
];

export const DEVICE_STATUSES: DeviceStatus[] = [
  "active",
  "inactive",
  "maintenance",
  "decommissioned",
];

export const GROUP_STATUSES: CrashGroupStatus[] = [
  "open",
  "investigating",
  "resolved",
  "ignored",
  "regressed",
];

export const SOURCE_TYPES: DocumentSourceType[] = [
  "stm32_reference",
  "freertos_doc",
  "arm_cortex_m",
  "engineering_note",
  "troubleshooting",
  "application_note",
  "previous_crash",
  "other",
];
