import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { ThemeToggle } from "../components/ThemeToggle";
import { NotificationBell } from "../components/NotificationBell";
import { Button } from "../components/Button";
import { cx } from "../lib/cx";
import type { RoleName } from "../api/types";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  roles?: RoleName[];
}

function Icon({ path }: { path: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: <Icon path="M4 13h6V4H4zM14 20h6V4h-6zM4 20h6v-4H4z" /> },
  { to: "/analytics", label: "Analytics", icon: <Icon path="M4 19V5M4 19h16M8 16v-5M12 16V8M16 16v-3" /> },
  { to: "/devices", label: "Devices", icon: <Icon path="M4 5h16v10H4zM8 19h8M12 15v4" /> },
  { to: "/crashes", label: "Crashes", icon: <Icon path="M12 2v6m0 0l3-3m-3 3L9 5M5 12a7 7 0 1014 0 7 7 0 00-14 0z" /> },
  { to: "/groups", label: "Crash Groups", icon: <Icon path="M4 6h16M4 12h16M4 18h10" /> },
  { to: "/knowledge-base", label: "Knowledge Base", icon: <Icon path="M4 5a2 2 0 012-2h11a1 1 0 011 1v14a1 1 0 01-1 1H6a2 2 0 01-2-2zM8 7h7M8 11h7" /> },
  { to: "/users", label: "Users", icon: <Icon path="M16 18v-1a4 4 0 00-8 0v1M12 11a3 3 0 100-6 3 3 0 000 6z" />, roles: ["admin"] },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { hasRole } = useAuth();
  const items = NAV.filter((n) => !n.roles || hasRole(...n.roles));
  return (
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-4 flex items-center gap-2 px-2 py-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white font-bold">
          B
        </div>
        <div className="leading-tight">
          <div className="font-semibold">BlackBox</div>
          <div className="text-[11px] text-muted">Crash Diagnosis</div>
        </div>
      </div>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cx(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-brand-600 text-white"
                : "text-[color:var(--text)] hover:surface-2",
            )
          }
        >
          {item.icon}
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const initials =
    (user?.full_name || user?.email || "?")
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0]?.toUpperCase())
      .join("") || "?";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex h-9 items-center gap-2 rounded-lg px-2 hover:surface-2"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-xs font-semibold text-white">
          {initials}
        </span>
        <span className="hidden max-w-[10rem] truncate text-sm sm:inline">
          {user?.full_name || user?.email}
        </span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="surface absolute right-0 z-20 mt-2 w-48 overflow-hidden rounded-lg border border-token shadow-lg">
            <div className="border-b border-token px-3 py-2">
              <div className="truncate text-sm font-medium">{user?.email}</div>
              <div className="mt-0.5 flex flex-wrap gap-1">
                {user?.roles.map((r) => (
                  <span key={r.id} className="text-[11px] capitalize text-muted">
                    {r.name}
                  </span>
                ))}
              </div>
            </div>
            <NavLink
              to="/profile"
              onClick={() => setOpen(false)}
              className="block px-3 py-2 text-sm hover:surface-2"
            >
              Profile
            </NavLink>
            <button
              onClick={() => {
                setOpen(false);
                void logout();
              }}
              className="block w-full px-3 py-2 text-left text-sm text-red-600 hover:surface-2"
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <div className="flex h-full">
      {/* Desktop sidebar */}
      <aside className="surface hidden w-60 shrink-0 border-r border-token md:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="presentation">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="surface absolute inset-y-0 left-0 w-60 border-r border-token">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="surface flex h-14 items-center justify-between gap-2 border-b border-token px-4">
          <Button
            variant="ghost"
            size="sm"
            className="md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
            </svg>
          </Button>
          <div className="flex-1" />
          <NotificationBell />
          <ThemeToggle />
          <UserMenu />
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
