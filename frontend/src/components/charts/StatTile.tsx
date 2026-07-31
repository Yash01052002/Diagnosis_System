import { Link } from "react-router-dom";
import { cx } from "../../lib/cx";

type Tone = "default" | "warning" | "danger" | "success";

const toneText: Record<Tone, string> = {
  default: "",
  warning: "text-amber-500",
  danger: "text-red-500",
  success: "text-emerald-500",
};

export function StatTile({
  label,
  value,
  hint,
  tone = "default",
  to,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: Tone;
  to?: string;
}) {
  const inner = (
    <>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={cx("mt-1 text-3xl font-semibold tabular-nums", toneText[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </>
  );
  const className =
    "surface block rounded-xl border border-token px-4 py-4 transition-colors";
  return to ? (
    <Link to={to} className={cx(className, "hover:surface-2")}>
      {inner}
    </Link>
  ) : (
    <div className={className}>{inner}</div>
  );
}
