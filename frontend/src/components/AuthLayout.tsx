import { ThemeToggle } from "./ThemeToggle";

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-col">
      <div className="flex items-center justify-between px-4 py-4">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">
            B
          </div>
          <span className="font-semibold">BlackBox</span>
        </div>
        <ThemeToggle />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 py-8">
        <div className="w-full max-w-md">
          <div className="surface rounded-2xl border border-token p-8 shadow-sm">
            <h1 className="text-xl font-semibold">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
            <div className="mt-6">{children}</div>
          </div>
          {footer && <div className="mt-4 text-center text-sm text-muted">{footer}</div>}
        </div>
      </div>
    </div>
  );
}
