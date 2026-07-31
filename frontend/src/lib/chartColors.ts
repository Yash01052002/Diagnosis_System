// Maps ordinal/status dimensions to chart CSS variables. Severity and
// confidence are states, so they use the reserved status hues (always shown
// with a text label beside the mark, never colour alone).
import type { ConfidenceLabel, CrashSeverity } from "../api/types";

export function severityColor(severity: string): string {
  const map: Record<CrashSeverity, string> = {
    low: "var(--chart-muted)",
    medium: "var(--chart-warning)",
    high: "var(--chart-serious)",
    critical: "var(--chart-critical)",
  };
  return map[severity as CrashSeverity] ?? "var(--chart-series-1)";
}

export function confidenceColor(label: string): string {
  const map: Record<ConfidenceLabel, string> = {
    certain: "var(--chart-good)",
    likely: "var(--chart-series-1)",
    uncertain: "var(--chart-warning)",
  };
  return map[label as ConfidenceLabel] ?? "var(--chart-series-1)";
}
