import { useRef, useState } from "react";

export interface TrendSeries {
  name: string;
  color: string;
  values: number[];
}

/**
 * Time-series line chart with an optional filled primary series and a crosshair
 * tooltip. One shared y-axis (never dual-axis). A legend is shown whenever there
 * is more than one series, so identity is never carried by colour alone.
 */
export function TrendChart({
  labels,
  series,
  height = 260,
}: {
  labels: string[];
  series: TrendSeries[];
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const W = 720;
  const H = height;
  const padL = 34;
  const padR = 14;
  const padT = 14;
  const padB = 26;
  const n = labels.length;

  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const x = (i: number) => (n <= 1 ? W / 2 : padL + (i / (n - 1)) * (W - padL - padR));
  const y = (v: number) => padT + (1 - v / max) * (H - padT - padB);
  const baseline = y(0);

  const gridVals = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(max * f));
  const uniqueGrid = Array.from(new Set(gridVals));

  function linePath(values: number[]): string {
    return values.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  }
  function areaPath(values: number[]): string {
    if (n === 0) return "";
    return (
      `M ${x(0).toFixed(1)} ${baseline.toFixed(1)} ` +
      values.map((v, i) => `L ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ") +
      ` L ${x(n - 1).toFixed(1)} ${baseline.toFixed(1)} Z`
    );
  }

  function onMove(e: React.PointerEvent) {
    const el = containerRef.current;
    if (!el || n === 0) return;
    const rect = el.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / rect.width;
    const idx = Math.min(n - 1, Math.max(0, Math.round(rel * (n - 1))));
    setHover(idx);
  }

  // X tick labels: first, middle, last only, to avoid crowding.
  const tickIdx = n <= 1 ? [0] : Array.from(new Set([0, Math.floor((n - 1) / 2), n - 1]));

  return (
    <div>
      {series.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-4">
          {series.map((s) => (
            <span key={s.name} className="flex items-center gap-1.5 text-xs text-muted">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <div
        ref={containerRef}
        className="relative w-full"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img">
          {/* gridlines */}
          {uniqueGrid.map((g) => (
            <g key={g}>
              <line
                x1={padL}
                x2={W - padR}
                y1={y(g)}
                y2={y(g)}
                stroke="var(--chart-grid)"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
              <text x={4} y={y(g) + 3} fontSize={10} fill="var(--chart-muted)">
                {g}
              </text>
            </g>
          ))}

          {/* primary series area (first series only) */}
          {series[0] && (
            <path d={areaPath(series[0].values)} fill={series[0].color} opacity={0.12} />
          )}

          {/* lines */}
          {series.map((s) => (
            <path
              key={s.name}
              d={linePath(s.values)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {/* crosshair + points at hover */}
          {hover !== null && (
            <>
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={padT}
                y2={baseline}
                stroke="var(--chart-axis)"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
              {series.map((s) => (
                <circle
                  key={s.name}
                  cx={x(hover)}
                  cy={y(s.values[hover] ?? 0)}
                  r={4}
                  fill={s.color}
                  stroke="var(--surface)"
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </>
          )}

          {/* x ticks */}
          {tickIdx.map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 6}
              fontSize={10}
              fill="var(--chart-muted)"
              textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}
            >
              {labels[i]?.slice(5) /* MM-DD */}
            </text>
          ))}
        </svg>

        {/* tooltip */}
        {hover !== null && (
          <div
            className="surface pointer-events-none absolute top-2 z-10 -translate-x-1/2 rounded-lg border border-token px-3 py-2 text-xs shadow-lg"
            style={{ left: `${n <= 1 ? 50 : (hover / (n - 1)) * 100}%` }}
          >
            <div className="mb-1 font-medium">{labels[hover]}</div>
            {series.map((s) => (
              <div key={s.name} className="flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                <span className="text-muted">{s.name}:</span>
                <span className="tabular-nums">{s.values[hover] ?? 0}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
