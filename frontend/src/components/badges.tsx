import { Badge } from "./Badge";
import { humanize } from "../lib/format";
import {
  confidenceTone,
  crashStatusTone,
  deviceStatusTone,
  documentStatusTone,
  groupStatusTone,
  severityTone,
} from "../lib/labels";
import type {
  ConfidenceLabel,
  CrashGroupStatus,
  CrashSeverity,
  CrashStatus,
  DeviceStatus,
  DocumentStatus,
} from "../api/types";

export const SeverityBadge = ({ value }: { value: CrashSeverity }) => (
  <Badge tone={severityTone[value]}>{value}</Badge>
);

export const CrashStatusBadge = ({ value }: { value: CrashStatus }) => (
  <Badge tone={crashStatusTone[value]}>{value}</Badge>
);

export const DeviceStatusBadge = ({ value }: { value: DeviceStatus }) => (
  <Badge tone={deviceStatusTone[value]}>{value}</Badge>
);

export const GroupStatusBadge = ({ value }: { value: CrashGroupStatus }) => (
  <Badge tone={groupStatusTone[value]}>{value}</Badge>
);

export const DocStatusBadge = ({ value }: { value: DocumentStatus }) => (
  <Badge tone={documentStatusTone[value]}>{value}</Badge>
);

export const ConfidenceBadge = ({ value }: { value: ConfidenceLabel }) => (
  <Badge tone={confidenceTone[value]}>{value}</Badge>
);

export const FaultBadge = ({ value }: { value: string }) => (
  <Badge tone="neutral">{humanize(value)}</Badge>
);
