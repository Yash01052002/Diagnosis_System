import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "../api/endpoints";
import { formatRelative } from "../lib/format";
import type { AppNotification } from "../api/types";

const levelDot: Record<string, string> = {
  info: "var(--chart-series-1)",
  warning: "var(--chart-warning)",
  critical: "var(--chart-critical)",
};

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Poll the unread count so a critical crash surfaces without a manual refresh.
  const count = useQuery({
    queryKey: ["notif-unread"],
    queryFn: notificationsApi.unreadCount,
    refetchInterval: 60_000,
  });

  const recent = useQuery({
    queryKey: ["notif-recent"],
    queryFn: () => notificationsApi.list({ page: 1, page_size: 6 }),
    enabled: open,
  });

  const markAll = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notif-unread"] });
      void queryClient.invalidateQueries({ queryKey: ["notif-recent"] });
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  function openNotification(n: AppNotification) {
    setOpen(false);
    if (n.resource_type === "crash_report" && n.resource_id) {
      navigate(`/crashes/${n.resource_id}`);
    } else {
      navigate("/notifications");
    }
  }

  const unread = count.data ?? 0;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-lg text-[color:var(--text)] hover:surface-2"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="surface absolute right-0 z-20 mt-2 w-80 overflow-hidden rounded-lg border border-token shadow-lg">
            <div className="flex items-center justify-between border-b border-token px-4 py-2">
              <span className="text-sm font-semibold">Notifications</span>
              {unread > 0 && (
                <button
                  onClick={() => markAll.mutate()}
                  className="text-xs text-brand-600 hover:underline"
                >
                  Mark all read
                </button>
              )}
            </div>
            <div className="max-h-96 overflow-y-auto">
              {recent.isLoading ? (
                <p className="px-4 py-6 text-center text-sm text-muted">Loading…</p>
              ) : recent.data && recent.data.items.length > 0 ? (
                recent.data.items.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => openNotification(n)}
                    className={
                      "flex w-full gap-2 border-b border-token px-4 py-3 text-left hover:surface-2 " +
                      (n.read_at ? "opacity-60" : "")
                    }
                  >
                    <span
                      className="mt-1 h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: levelDot[n.level] ?? "var(--chart-muted)" }}
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{n.title}</span>
                      <span className="line-clamp-2 text-xs text-muted">{n.body}</span>
                      <span className="text-[11px] text-muted">{formatRelative(n.created_at)}</span>
                    </span>
                  </button>
                ))
              ) : (
                <p className="px-4 py-6 text-center text-sm text-muted">You're all caught up.</p>
              )}
            </div>
            <Link
              to="/notifications"
              onClick={() => setOpen(false)}
              className="block border-t border-token px-4 py-2 text-center text-sm text-brand-600 hover:surface-2"
            >
              View all
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
