import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { formatRelative, humanize } from "../lib/format";
import { CRASH_SEVERITIES } from "../lib/labels";
import { PageHeader } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { Select } from "../components/Input";
import { Badge } from "../components/Badge";
import { Pagination } from "../components/Pagination";
import { Alert, EmptyState, ErrorState, LoadingState } from "../components/feedback";
import type { AlertSettings, AppNotification, NotificationLevel } from "../api/types";

const levelTone: Record<NotificationLevel, "info" | "warning" | "danger"> = {
  info: "info",
  warning: "warning",
  critical: "danger",
};

export function NotificationsPage() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["notifications", { unreadOnly, page }],
    queryFn: () =>
      notificationsApi.list({ unread_only: unreadOnly, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => invalidate(),
  });
  const markAll = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => invalidate(),
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    void queryClient.invalidateQueries({ queryKey: ["notif-unread"] });
    void queryClient.invalidateQueries({ queryKey: ["notif-recent"] });
  }

  function open(n: AppNotification) {
    if (!n.read_at) markRead.mutate(n.id);
    if (n.resource_type === "crash_report" && n.resource_id) {
      navigate(`/crashes/${n.resource_id}`);
    }
  }

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Alerts and platform messages."
        actions={
          <Button variant="secondary" size="sm" onClick={() => markAll.mutate()}>
            Mark all read
          </Button>
        }
      />

      {isAdmin && <AlertSettingsCard />}

      <Card>
        <CardHeader
          title="Inbox"
          actions={
            <Select
              value={unreadOnly ? "unread" : "all"}
              onChange={(e) => {
                setUnreadOnly(e.target.value === "unread");
                setPage(1);
              }}
              className="w-36"
            >
              <option value="all">All</option>
              <option value="unread">Unread only</option>
            </Select>
          }
        />
        <CardBody className="p-0">
          {query.isLoading ? (
            <LoadingState />
          ) : query.isError ? (
            <ErrorState message={errorMessage(query.error)} onRetry={() => query.refetch()} />
          ) : query.data && query.data.items.length > 0 ? (
            <>
              <ul className="divide-y divide-[color:var(--border)]">
                {query.data.items.map((n) => (
                  <li key={n.id}>
                    <button
                      onClick={() => open(n)}
                      className={
                        "flex w-full items-start gap-3 px-5 py-4 text-left hover:surface-2 " +
                        (n.read_at ? "opacity-70" : "")
                      }
                    >
                      {!n.read_at && (
                        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand-500" />
                      )}
                      <span className={"min-w-0 flex-1 " + (n.read_at ? "pl-5" : "")}>
                        <span className="flex items-center gap-2">
                          <span className="font-medium">{n.title}</span>
                          <Badge tone={levelTone[n.level]}>{n.level}</Badge>
                        </span>
                        <span className="mt-0.5 block text-sm text-muted">{n.body}</span>
                        <span className="mt-1 block text-xs text-muted">
                          {formatRelative(n.created_at)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="px-3">
                <Pagination
                  page={query.data.page}
                  pages={query.data.pages}
                  total={query.data.total}
                  onChange={setPage}
                />
              </div>
            </>
          ) : (
            <div className="py-10">
              <EmptyState title="No notifications" hint="You're all caught up." />
            </div>
          )}
        </CardBody>
      </Card>
    </>
  );
}

function AlertSettingsCard() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["alert-settings"], queryFn: notificationsApi.getSettings });
  const [draft, setDraft] = useState<AlertSettings | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const settings = draft ?? query.data;

  const save = useMutation({
    mutationFn: (body: Partial<AlertSettings>) => notificationsApi.updateSettings(body),
    onSuccess: (updated) => {
      setDraft(updated);
      setMsg("Alert settings saved.");
      void queryClient.invalidateQueries({ queryKey: ["alert-settings"] });
    },
  });

  if (query.isLoading || !settings) {
    return (
      <Card className="mb-6">
        <CardHeader title="Alert settings" />
        <CardBody>
          <LoadingState label="Loading settings…" />
        </CardBody>
      </Card>
    );
  }

  const set = (patch: Partial<AlertSettings>) => setDraft({ ...settings, ...patch });

  return (
    <Card className="mb-6">
      <CardHeader
        title="Alert settings"
        subtitle="When a crash raises an alert, and who receives it."
      />
      <CardBody className="flex flex-col gap-4">
        {msg && <Alert tone="success">{msg}</Alert>}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings.enabled}
            onChange={(e) => set({ enabled: e.target.checked })}
            className="h-4 w-4"
          />
          Raise in-app alerts on new crashes
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings.email_enabled}
            onChange={(e) => set({ email_enabled: e.target.checked })}
            className="h-4 w-4"
          />
          Also send alert emails
        </label>
        <div className="max-w-xs">
          <Select
            label="Minimum severity"
            value={settings.min_severity}
            onChange={(e) => set({ min_severity: e.target.value as AlertSettings["min_severity"] })}
          >
            {CRASH_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <div className="mb-1 text-sm font-medium">Recipients</div>
          <div className="flex flex-wrap gap-2">
            {(["admin", "engineer", "viewer"] as const).map((role) => {
              const active = settings.recipient_roles.includes(role);
              return (
                <button
                  key={role}
                  type="button"
                  onClick={() =>
                    set({
                      recipient_roles: active
                        ? settings.recipient_roles.filter((r) => r !== role)
                        : [...settings.recipient_roles, role],
                    })
                  }
                  className={
                    "rounded-full border px-3 py-1 text-sm capitalize " +
                    (active
                      ? "border-brand-600 bg-brand-600 text-white"
                      : "border-token text-muted hover:surface-2")
                  }
                >
                  {role}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <Button
            onClick={() => {
              setMsg(null);
              save.mutate(settings);
            }}
            loading={save.isPending}
          >
            Save settings
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
