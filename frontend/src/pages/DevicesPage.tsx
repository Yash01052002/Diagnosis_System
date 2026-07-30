import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { devicesApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { useDebounce } from "../lib/useDebounce";
import { DEVICE_STATUSES } from "../lib/labels";
import { formatRelative, humanize } from "../lib/format";
import { PageHeader } from "../components/page";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Input, Select } from "../components/Input";
import { Modal } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { DeviceStatusBadge } from "../components/badges";
import { Alert, EmptyState, ErrorState, LoadingState } from "../components/feedback";

export function DevicesPage() {
  const navigate = useNavigate();
  const { isEngineer } = useAuth();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const q = useDebounce(search);

  const query = useQuery({
    queryKey: ["devices", { q, status, page }],
    queryFn: () => devicesApi.list({ q, status, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Devices"
        subtitle="Registered STM32 devices reporting to the platform."
        actions={
          isEngineer && (
            <Button onClick={() => setShowCreate(true)}>Register device</Button>
          )
        }
      />

      <Card className="mb-4 p-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input
            placeholder="Search by device id, serial, model…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="sm:max-w-xs"
          />
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="sm:max-w-[12rem]"
          >
            <option value="">All statuses</option>
            {DEVICE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      <Card>
        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState message={errorMessage(query.error)} onRetry={() => query.refetch()} />
        ) : query.data && query.data.items.length > 0 ? (
          <>
            <Table>
              <THead>
                <TR>
                  <TH>Device</TH>
                  <TH>Model</TH>
                  <TH>Firmware</TH>
                  <TH>Status</TH>
                  <TH>Last online</TH>
                  <TH>Tags</TH>
                </TR>
              </THead>
              <TBody>
                {query.data.items.map((d) => (
                  <TR key={d.id} onClick={() => navigate(`/devices/${d.id}`)}>
                    <TD>
                      <div className="font-medium">{d.device_id}</div>
                      <div className="text-xs text-muted">{d.serial_number}</div>
                    </TD>
                    <TD>{d.hardware_model}</TD>
                    <TD>{d.firmware_version}</TD>
                    <TD>
                      <DeviceStatusBadge value={d.status} />
                    </TD>
                    <TD className="text-muted">{formatRelative(d.last_online_at)}</TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        {d.tags.slice(0, 3).map((t) => (
                          <span
                            key={t}
                            className="rounded-full bg-[var(--surface-2)] px-2 py-0.5 text-xs text-muted"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
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
          <EmptyState
            title="No devices found"
            hint="Adjust your filters, or register a device if the fleet is empty."
          />
        )}
      </Card>

      {showCreate && (
        <CreateDeviceModal onClose={() => setShowCreate(false)} onCreated={(id) => navigate(`/devices/${id}`)} />
      )}
    </>
  );
}

function CreateDeviceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    device_id: "",
    serial_number: "",
    hardware_model: "STM32F407VG",
    firmware_version: "",
    location: "",
    tags: "",
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      devicesApi.create({
        device_id: form.device_id,
        serial_number: form.serial_number,
        hardware_model: form.hardware_model,
        firmware_version: form.firmware_version,
        location: form.location || undefined,
        tags: form.tags
          ? form.tags.split(",").map((t) => t.trim()).filter(Boolean)
          : [],
      }),
    onSuccess: (device) => {
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      onCreated(device.id);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <Modal
      open
      title="Register device"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
            loading={mutation.isPending}
          >
            Register
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Alert>{error}</Alert>}
        <Input label="Device ID" value={form.device_id} onChange={set("device_id")} placeholder="STM32-F4-0001" required />
        <Input label="Serial number" value={form.serial_number} onChange={set("serial_number")} placeholder="SN-2026-000123" required />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Hardware model" value={form.hardware_model} onChange={set("hardware_model")} />
          <Input label="Firmware version" value={form.firmware_version} onChange={set("firmware_version")} placeholder="1.4.2" required />
        </div>
        <Input label="Location" value={form.location} onChange={set("location")} placeholder="Lab A, Rack 3" />
        <Input label="Tags" value={form.tags} onChange={set("tags")} hint="Comma-separated, e.g. field-trial, eu-west" />
      </div>
    </Modal>
  );
}
