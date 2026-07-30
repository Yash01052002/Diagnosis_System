import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { crashesApi, devicesApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { DEVICE_STATUSES } from "../lib/labels";
import { formatDateTime, formatRelative, humanize, toHex } from "../lib/format";
import { PageHeader, DescriptionList } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { Input, Select } from "../components/Input";
import { Modal, ConfirmDialog } from "../components/Modal";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { DeviceStatusBadge, SeverityBadge, CrashStatusBadge, FaultBadge } from "../components/badges";
import { Alert, EmptyState, ErrorState, LoadingState } from "../components/feedback";
import type { DeviceApiKeyCreated } from "../api/types";

export function DeviceDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { isEngineer, isAdmin } = useAuth();
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const device = useQuery({ queryKey: ["device", id], queryFn: () => devicesApi.get(id) });
  const stats = useQuery({ queryKey: ["device-stats", id], queryFn: () => devicesApi.stats(id) });

  const deleteMutation = useMutation({
    mutationFn: () => devicesApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      navigate("/devices");
    },
  });

  if (device.isLoading) return <LoadingState />;
  if (device.isError || !device.data)
    return <ErrorState message={errorMessage(device.error)} onRetry={() => device.refetch()} />;

  const d = device.data;

  return (
    <>
      <PageHeader
        title={d.device_id}
        subtitle={`${d.hardware_model} · ${d.serial_number}`}
        back={{ to: "/devices", label: "Devices" }}
        actions={
          <>
            {isEngineer && (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            {isAdmin && (
              <Button variant="danger" onClick={() => setConfirmDelete(true)}>
                Delete
              </Button>
            )}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Details" actions={<DeviceStatusBadge value={d.status} />} />
          <CardBody>
            <DescriptionList
              items={[
                { label: "Device ID", value: d.device_id },
                { label: "Serial number", value: d.serial_number },
                { label: "Hardware model", value: d.hardware_model },
                { label: "Firmware version", value: d.firmware_version },
                { label: "Location", value: d.location || "—" },
                { label: "Owner", value: d.owner?.email || "—" },
                { label: "Last online", value: formatRelative(d.last_online_at) },
                { label: "Registered", value: formatDateTime(d.created_at) },
                {
                  label: "Tags",
                  value: d.tags.length ? (
                    <div className="flex flex-wrap gap-1">
                      {d.tags.map((t) => (
                        <span key={t} className="rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-xs">
                          {t}
                        </span>
                      ))}
                    </div>
                  ) : (
                    "—"
                  ),
                },
                { label: "Description", value: d.description || "—" },
              ]}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Crash activity" />
          <CardBody>
            {stats.data ? (
              <div className="grid grid-cols-2 gap-4">
                <Stat label="Total crashes" value={stats.data.total_crashes} />
                <Stat label="Open" value={stats.data.open_crashes} tone="warning" />
                <Stat label="Last 24h" value={stats.data.crashes_last_24h} />
                <Stat label="Last crash" value={formatRelative(stats.data.last_crash_at)} small />
              </div>
            ) : (
              <LoadingState label="Loading stats…" />
            )}
          </CardBody>
        </Card>
      </div>

      {isEngineer && <ApiKeysCard deviceId={id} />}

      <RecentCrashes deviceId={d.device_id} />

      {editing && <EditDeviceModal device={d} onClose={() => setEditing(false)} />}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete device"
        danger
        confirmLabel="Delete device"
        loading={deleteMutation.isPending}
        message={
          <>
            Deleting <strong>{d.device_id}</strong> also removes its crash
            reports and API keys. This cannot be undone.
          </>
        }
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => deleteMutation.mutate()}
      />
    </>
  );
}

function Stat({
  label,
  value,
  tone,
  small,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "warning";
  small?: boolean;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div
        className={
          small
            ? "mt-1 text-sm font-medium"
            : tone === "warning"
              ? "mt-1 text-2xl font-semibold text-amber-500"
              : "mt-1 text-2xl font-semibold"
        }
      >
        {value}
      </div>
    </div>
  );
}

function EditDeviceModal({ device, onClose }: { device: import("../api/types").Device; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    firmware_version: device.firmware_version,
    status: device.status,
    location: device.location ?? "",
    tags: device.tags.join(", "),
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      devicesApi.update(device.id, {
        firmware_version: form.firmware_version,
        status: form.status,
        location: form.location || null,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["device", device.id] });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal
      open
      title="Edit device"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} loading={mutation.isPending}>
            Save
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Alert>{error}</Alert>}
        <Input
          label="Firmware version"
          value={form.firmware_version}
          onChange={(e) => setForm((f) => ({ ...f, firmware_version: e.target.value }))}
        />
        <Select
          label="Status"
          value={form.status}
          onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as typeof f.status }))}
        >
          {DEVICE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </Select>
        <Input
          label="Location"
          value={form.location}
          onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
        />
        <Input
          label="Tags"
          value={form.tags}
          onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
          hint="Comma-separated"
        />
      </div>
    </Modal>
  );
}

function ApiKeysCard({ deviceId }: { deviceId: string }) {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [keyName, setKeyName] = useState("");
  const [created, setCreated] = useState<DeviceApiKeyCreated | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);

  const keys = useQuery({
    queryKey: ["device-keys", deviceId],
    queryFn: () => devicesApi.apiKeys(deviceId),
  });

  const createMutation = useMutation({
    mutationFn: () => devicesApi.createApiKey(deviceId, keyName),
    onSuccess: (key) => {
      setCreated(key);
      setShowCreate(false);
      setKeyName("");
      void queryClient.invalidateQueries({ queryKey: ["device-keys", deviceId] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => devicesApi.revokeApiKey(deviceId, keyId),
    onSuccess: () => {
      setRevokeId(null);
      void queryClient.invalidateQueries({ queryKey: ["device-keys", deviceId] });
    },
  });

  return (
    <Card className="mt-6">
      <CardHeader
        title="API keys"
        subtitle="Keys let this device authenticate crash uploads."
        actions={
          <Button size="sm" onClick={() => setShowCreate(true)}>
            New key
          </Button>
        }
      />
      <CardBody>
        {keys.isLoading ? (
          <LoadingState label="Loading keys…" />
        ) : keys.data && keys.data.length > 0 ? (
          <Table>
            <THead>
              <TR>
                <TH>Name</TH>
                <TH>Prefix</TH>
                <TH>Created</TH>
                <TH>Last used</TH>
                <TH>State</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {keys.data.map((k) => (
                <TR key={k.id}>
                  <TD className="font-medium">{k.name}</TD>
                  <TD className="font-mono text-xs">{k.prefix}</TD>
                  <TD className="text-muted">{formatDateTime(k.created_at)}</TD>
                  <TD className="text-muted">{formatRelative(k.last_used_at)}</TD>
                  <TD>
                    {k.revoked_at ? (
                      <span className="text-xs text-red-500">revoked</span>
                    ) : (
                      <span className="text-xs text-emerald-500">active</span>
                    )}
                  </TD>
                  <TD>
                    {!k.revoked_at && (
                      <Button size="sm" variant="ghost" onClick={() => setRevokeId(k.id)}>
                        Revoke
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <EmptyState title="No API keys" hint="Create a key so this device can submit crashes." />
        )}
      </CardBody>

      <Modal
        open={showCreate}
        title="Create API key"
        onClose={() => setShowCreate(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
            <Button onClick={() => createMutation.mutate()} loading={createMutation.isPending} disabled={!keyName}>
              Create
            </Button>
          </>
        }
      >
        <Input label="Key name" value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="field-trial-fleet" />
      </Modal>

      <Modal
        open={Boolean(created)}
        title="API key created"
        onClose={() => setCreated(null)}
        footer={
          <Button onClick={() => setCreated(null)}>Done</Button>
        }
      >
        <div className="flex flex-col gap-3">
          <Alert tone="info">
            Copy this key now — it is shown once and cannot be retrieved again.
          </Alert>
          <code className="scrollbar-thin block overflow-x-auto rounded-lg bg-[var(--surface-2)] p-3 font-mono text-xs">
            {created?.api_key}
          </code>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(revokeId)}
        title="Revoke API key"
        danger
        confirmLabel="Revoke"
        loading={revokeMutation.isPending}
        message="Firmware using this key will no longer be able to submit crashes."
        onCancel={() => setRevokeId(null)}
        onConfirm={() => revokeId && revokeMutation.mutate(revokeId)}
      />
    </Card>
  );
}

function RecentCrashes({ deviceId }: { deviceId: string }) {
  const navigate = useNavigate();
  const crashes = useQuery({
    queryKey: ["device-crashes", deviceId],
    queryFn: () => crashesApi.list({ device: deviceId, page: 1, page_size: 10 }),
  });

  return (
    <Card className="mt-6">
      <CardHeader
        title="Recent crashes"
        actions={
          <Link to={`/crashes?device=${encodeURIComponent(deviceId)}`} className="text-sm text-brand-600 hover:underline">
            View all
          </Link>
        }
      />
      <CardBody className="p-0">
        {crashes.isLoading ? (
          <LoadingState label="Loading crashes…" />
        ) : crashes.data && crashes.data.items.length > 0 ? (
          <Table>
            <THead>
              <TR>
                <TH>When</TH>
                <TH>Fault</TH>
                <TH>Function</TH>
                <TH>Severity</TH>
                <TH>Status</TH>
              </TR>
            </THead>
            <TBody>
              {crashes.data.items.map((c) => (
                <TR key={c.id} onClick={() => navigate(`/crashes/${c.id}`)}>
                  <TD>{formatDateTime(c.occurred_at)}</TD>
                  <TD>
                    <FaultBadge value={c.fault_type} />
                  </TD>
                  <TD className="font-mono text-xs">{c.top_function || toHex(c.program_counter)}</TD>
                  <TD>
                    <SeverityBadge value={c.severity} />
                  </TD>
                  <TD>
                    <CrashStatusBadge value={c.status} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <div className="py-10">
            <EmptyState title="No crashes reported" hint="This device has a clean record." />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
