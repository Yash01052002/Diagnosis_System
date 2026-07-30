// Formatting helpers shared across screens.

export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

/** "3 minutes ago", "2 days ago", … relative to now. */
export function formatRelative(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const seconds = Math.round((Date.now() - d.getTime()) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const table: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [604800, "day"],
    [2629800, "week"],
    [31557600, "month"],
    [Infinity, "year"],
  ];
  const divisors: Record<string, number> = {
    second: 1,
    minute: 60,
    hour: 3600,
    day: 86400,
    week: 604800,
    month: 2629800,
    year: 31557600,
  };
  for (const [limit, unit] of table) {
    if (abs < limit) {
      return rtf.format(-Math.round(seconds / divisors[unit]), unit);
    }
  }
  return "—";
}

/** Render a 32-bit address as 0x-padded hex. */
export function toHex(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return "0x" + value.toString(16).toUpperCase().padStart(8, "0");
}

/** "hard_fault" -> "Hard Fault". */
export function humanize(value?: string | null): string {
  if (!value) return "—";
  return value
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function percent(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}
