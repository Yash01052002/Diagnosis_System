import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { groupsApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { GROUP_STATUSES } from "../lib/labels";
import { formatDateTime, humanize } from "../lib/format";
import { PageHeader, DescriptionList, Mono } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { Select, Textarea } from "../components/Input";
import { Modal } from "../components/Modal";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import {
  CrashStatusBadge,
  FaultBadge,
  GroupStatusBadge,
  SeverityBadge,
} from "../components/badges";
import { Alert, ErrorState, LoadingState } from "../components/feedback";
import type { CrashGroup } from "../api/types";

export function GroupDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { isEngineer } = useAuth();
  const [editing, setEditing] = useState(false);

  const group = useQuery({ queryKey: ["group", id], queryFn: () => groupsApi.get(id) });
  const crashes = useQuery({
    queryKey: ["group-crashes", id],
    queryFn: () => groupsApi.crashes(id, 1, 20),
  });

  if (group.isLoading) return <LoadingState />;
  if (group.isError || !group.data)
    return <ErrorState message={errorMessage(group.error)} onRetry={() => group.refetch()} />;

  const g = group.data;

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            <span className="truncate">{g.title}</span>
            <SeverityBadge value={g.severity} />
            <GroupStatusBadge value={g.status} />
          </span>
        }
        subtitle={`Seen ${g.occurrence_count.toLocaleString()} times across ${g.device_count.toLocaleString()} device(s)`}
        back={{ to: "/groups", label: "Crash groups" }}
        actions={
          isEngineer && (
            <Button variant="secondary" onClick={() => setEditing(true)}>
              Triage bug
            </Button>
          )
        }
      />

      {g.status === "regressed" && (
        <div className="mb-4">
          <Alert>
            This bug regressed{g.regressed_at ? ` on ${formatDateTime(g.regressed_at)}` : ""} —
            a matching crash arrived after it was marked resolved.
          </Alert>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="Bug details" />
          <CardBody>
            <DescriptionList
              className="grid-cols-1"
              items={[
                { label: "Fault type", value: <FaultBadge value={g.fault_type} /> },
                { label: "Task", value: g.task_name || "—" },
                { label: "Top function", value: g.top_function ? <Mono>{g.top_function}</Mono> : "—" },
                { label: "Signature", value: <Mono>{g.signature.slice(0, 20)}…</Mono> },
                { label: "First seen", value: formatDateTime(g.first_seen_at) },
                { label: "Last seen", value: formatDateTime(g.last_seen_at) },
                {
                  label: "Affected firmware",
                  value: g.affected_firmware_versions.length
                    ? g.affected_firmware_versions.join(", ")
                    : "—",
                },
                { label: "Notes", value: g.notes || "—" },
              ]}
            />
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Occurrences" subtitle="Individual crash reports in this group." />
          <CardBody className="p-0">
            {crashes.isLoading ? (
              <LoadingState label="Loading occurrences…" />
            ) : crashes.data && crashes.data.items.length > 0 ? (
              <Table>
                <THead>
                  <TR>
                    <TH>When</TH>
                    <TH>Device</TH>
                    <TH>Firmware</TH>
                    <TH>Severity</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {crashes.data.items.map((c) => (
                    <TR key={c.id} onClick={() => navigate(`/crashes/${c.id}`)}>
                      <TD>{formatDateTime(c.occurred_at)}</TD>
                      <TD className="font-medium">{c.device.device_id}</TD>
                      <TD>{c.firmware_version}</TD>
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
              <div className="py-8 text-center text-sm text-muted">No occurrences found.</div>
            )}
          </CardBody>
        </Card>
      </div>

      {editing && <TriageGroupModal group={g} onClose={() => setEditing(false)} />}
    </>
  );
}

function TriageGroupModal({ group: g, onClose }: { group: CrashGroup; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState(g.status);
  const [notes, setNotes] = useState(g.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => groupsApi.update(g.id, { status, notes }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["group", g.id] });
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal
      open
      title="Triage bug"
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
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          {GROUP_STATUSES.map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </Select>
        <Textarea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} />
        <p className="text-xs text-muted">
          Marking a bug resolved is a claim about the fix. If a matching crash
          arrives later, it flips back to regressed automatically.
        </p>
      </div>
    </Modal>
  );
}
