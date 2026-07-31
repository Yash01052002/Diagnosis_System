import { humanize } from "../../lib/format";

export interface BarDatum {
  label: string;
  value: number;
  /** CSS color for this bar's fill. Defaults to the sequential series hue. */
  color?: string;
  /** Optional secondary text shown under the label. */
  sub?: string;
}

/**
 * Horizontal bar chart for a single magnitude series. Category identity lives
 * in the row labels, so one hue is correct (per the data-viz color formula);
 * callers pass per-bar `color` only for status-coded dimensions (severity,
 * confidence), where every bar is also labelled.
 */
export function BarChart({
  data,
  humanizeLabels = true,
  formatValue = (v) => v.toLocaleString(),
  emptyLabel = "No data",
}: {
  data: BarDatum[];
  humanizeLabels?: boolean;
  formatValue?: (value: number) => string;
  emptyLabel?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">{emptyLabel}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {data.map((d) => {
        const pct = Math.max(2, Math.round((d.value / max) * 100));
        const label = humanizeLabels ? humanize(d.label) : d.label;
        return (
          <div key={d.label} className="grid grid-cols-[8rem_1fr_auto] items-center gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm" title={label}>
                {label}
              </div>
              {d.sub && <div className="truncate text-xs text-muted">{d.sub}</div>}
            </div>
            <div
              className="h-2.5 overflow-hidden rounded-full"
              style={{ backgroundColor: "var(--surface-2)" }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${pct}%`,
                  backgroundColor: d.color ?? "var(--chart-series-1)",
                }}
                title={`${label}: ${formatValue(d.value)}`}
              />
            </div>
            <div className="w-12 text-right text-sm tabular-nums">{formatValue(d.value)}</div>
          </div>
        );
      })}
    </div>
  );
}
