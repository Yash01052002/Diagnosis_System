import { cx } from "../lib/cx";
import type { Tone } from "../lib/labels";

const tones: Record<Tone, string> = {
  neutral:
    "bg-slate-100 text-slate-700 dark:bg-slate-700/40 dark:text-slate-300",
  brand: "bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-300",
  success:
    "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300",
  warning:
    "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300",
  danger: "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300",
  info: "bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300",
  purple:
    "bg-violet-100 text-violet-700 dark:bg-violet-500/20 dark:text-violet-300",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
