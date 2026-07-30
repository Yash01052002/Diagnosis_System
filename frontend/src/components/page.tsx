import { Link } from "react-router-dom";
import { cx } from "../lib/cx";

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  back?: { to: string; label: string };
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back && (
          <Link
            to={back.to}
            className="mb-1 inline-flex items-center gap-1 text-sm text-muted hover:text-brand-600"
          >
            <span aria-hidden>←</span> {back.label}
          </Link>
        )}
        <h1 className="truncate text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function DescriptionList({
  items,
  className,
}: {
  items: Array<{ label: string; value: React.ReactNode }>;
  className?: string;
}) {
  return (
    <dl className={cx("grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2", className)}>
      {items.map((item, i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs uppercase tracking-wide text-muted">{item.label}</dt>
          <dd className="mt-0.5 break-words text-sm">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Monospace value, e.g. an address or a signature. */
export function Mono({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[13px] text-[color:var(--text)]">{children}</span>
  );
}
