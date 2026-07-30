import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { crashesApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { CRASH_SEVERITIES, CRASH_STATUSES } from "../lib/labels";
import { formatDateTime, humanize, percent, toHex } from "../lib/format";
import { PageHeader, DescriptionList, Mono } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { Select, Textarea } from "../components/Input";
import { Modal, ConfirmDialog } from "../components/Modal";
import {
  ConfidenceBadge,
  CrashStatusBadge,
  FaultBadge,
  SeverityBadge,
} from "../components/badges";
import { Alert, ErrorState, LoadingState } from "../components/feedback";
import type { Crash, Diagnosis, Frame } from "../api/types";

export function CrashDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { isEngineer, isAdmin } = useAuth();
  const [triage, setTriage] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const crash = useQuery({ queryKey: ["crash", id], queryFn: () => crashesApi.get(id) });

  const symbolicate = useMutation({
    mutationFn: () => crashesApi.symbolicate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["crash", id] }),
    onError: (err) => setActionError(errorMessage(err)),
  });

  const remove = useMutation({
    mutationFn: () => crashesApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["crashes"] });
      navigate("/crashes");
    },
  });

  if (crash.isLoading) return <LoadingState />;
  if (crash.isError || !crash.data)
    return <ErrorState message={errorMessage(crash.error)} onRetry={() => crash.refetch()} />;

  const c = crash.data;

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            {humanize(c.fault_type)}
            <SeverityBadge value={c.severity} />
            <CrashStatusBadge value={c.status} />
          </span>
        }
        subtitle={
          <>
            on{" "}
            <Link to={`/devices/${c.device.id}`} className="text-brand-600 hover:underline">
              {c.device.device_id}
            </Link>{" "}
            · {formatDateTime(c.occurred_at)}
          </>
        }
        back={{ to: "/crashes", label: "Crashes" }}
        actions={
          <>
            {isEngineer && (
              <>
                <Button variant="secondary" onClick={() => setTriage(true)}>
                  Triage
                </Button>
                <Button
                  variant="secondary"
                  loading={symbolicate.isPending}
                  onClick={() => {
                    setActionError(null);
                    symbolicate.mutate();
                  }}
                >
                  Re-symbolize
                </Button>
              </>
            )}
            {isAdmin && (
              <Button variant="danger" onClick={() => setConfirmDelete(true)}>
                Delete
              </Button>
            )}
          </>
        }
      />

      {actionError && (
        <div className="mb-4">
          <Alert>{actionError}</Alert>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <StackTracePanel crash={c} />
          <DiagnosisPanel crashId={id} canDiagnose={isEngineer} />
          <RawDumps crash={c} />
        </div>

        <div className="flex flex-col gap-6">
          <FactsCard crash={c} />
          {c.notes && (
            <Card>
              <CardHeader title="Triage notes" />
              <CardBody>
                <p className="whitespace-pre-wrap text-sm">{c.notes}</p>
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      {triage && <TriageModal crash={c} onClose={() => setTriage(false)} />}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete crash report"
        danger
        confirmLabel="Delete"
        loading={remove.isPending}
        message="This permanently removes the crash report and its evidence."
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

function FactsCard({ crash: c }: { crash: Crash }) {
  return (
    <Card>
      <CardHeader title="Crash facts" />
      <CardBody>
        <DescriptionList
          className="grid-cols-1"
          items={[
            { label: "Fault type", value: <FaultBadge value={c.fault_type} /> },
            { label: "Exception", value: c.exception_type || "—" },
            { label: "Task", value: c.task_name || "—" },
            { label: "Firmware", value: c.firmware_version },
            { label: "Build", value: c.build_version || "—" },
            { label: "Program counter", value: <Mono>{toHex(c.program_counter)}</Mono> },
            { label: "Link register", value: <Mono>{toHex(c.link_register)}</Mono> },
            { label: "Stack pointer", value: <Mono>{toHex(c.stack_pointer)}</Mono> },
            {
              label: "Crash group",
              value: c.group ? (
                <Link to={`/groups/${c.group.id}`} className="text-brand-600 hover:underline">
                  {c.group.title}
                </Link>
              ) : (
                "—"
              ),
            },
            {
              label: "Signature",
              value: c.crash_signature ? <Mono>{c.crash_signature.slice(0, 16)}…</Mono> : "—",
            },
            { label: "Received", value: formatDateTime(c.received_at) },
          ]}
        />
      </CardBody>
    </Card>
  );
}

function FrameRow({ frame, index }: { frame: Frame; index: number }) {
  return (
    <li className="flex items-start gap-3 px-4 py-2 font-mono text-[13px]">
      <span className="w-6 shrink-0 select-none text-right text-muted">{index}</span>
      <span className="w-10 shrink-0 text-[11px] uppercase text-muted">{frame.origin}</span>
      <span className="min-w-0 flex-1 break-words">
        {frame.resolved ? (
          <>
            <span className="text-brand-600 dark:text-brand-300">
              {frame.function}
              {frame.offset ? `+0x${frame.offset.toString(16)}` : ""}
            </span>
            {frame.source_file && (
              <span className="text-muted">
                {" "}
                at {frame.source_file}
                {frame.line ? `:${frame.line}` : ""}
              </span>
            )}
            {frame.inlined && <span className="ml-2 text-[11px] text-violet-500">inlined</span>}
          </>
        ) : (
          <span className="text-muted">{frame.address_hex} (unresolved)</span>
        )}
      </span>
    </li>
  );
}

function StackTracePanel({ crash: c }: { crash: Crash }) {
  const sym = c.symbolication;
  return (
    <Card>
      <CardHeader
        title="Symbolized stack trace"
        subtitle={
          c.top_function
            ? `Faulting function: ${c.top_function}`
            : "Address → function → source line"
        }
        actions={
          sym?.symbolized ? (
            <span className="text-xs text-muted">
              {sym.resolved_count}/{sym.frame_count} frames resolved
            </span>
          ) : null
        }
      />
      <CardBody className="p-0">
        {sym && sym.frames.length > 0 ? (
          <ol className="divide-y divide-[color:var(--border)]">
            {sym.frames.map((f, i) => (
              <FrameRow key={i} frame={f} index={i} />
            ))}
          </ol>
        ) : (
          <div className="px-4 py-8 text-center text-sm text-muted">
            No symbolized frames. Upload a matching firmware build (ELF/MAP) and
            re-symbolize to resolve the addresses.
          </div>
        )}
        {sym?.warnings && sym.warnings.length > 0 && (
          <div className="border-t border-token px-4 py-3">
            {sym.warnings.map((w, i) => (
              <p key={i} className="text-xs text-amber-600 dark:text-amber-400">
                {w}
              </p>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function DiagnosisPanel({ crashId, canDiagnose }: { crashId: string; canDiagnose: boolean }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["diagnoses", crashId],
    queryFn: () => crashesApi.diagnoses(crashId),
  });

  const diagnose = useMutation({
    mutationFn: () => crashesApi.diagnose(crashId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["diagnoses", crashId] }),
    onError: (err) => setError(errorMessage(err)),
  });

  const latest = history.data?.[0];

  return (
    <Card>
      <CardHeader
        title="AI diagnosis"
        subtitle="Retrieval-augmented, grounded in the knowledge base."
        actions={
          canDiagnose && (
            <Button
              size="sm"
              loading={diagnose.isPending}
              onClick={() => {
                setError(null);
                diagnose.mutate();
              }}
            >
              {latest ? "Re-run diagnosis" : "Diagnose"}
            </Button>
          )
        }
      />
      <CardBody>
        {error && (
          <div className="mb-4">
            <Alert>{error}</Alert>
          </div>
        )}
        {history.isLoading ? (
          <LoadingState label="Loading diagnoses…" />
        ) : latest ? (
          <div className="flex flex-col gap-6">
            <DiagnosisView diagnosis={latest} />
            {history.data && history.data.length > 1 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted hover:text-brand-600">
                  {history.data.length - 1} earlier{" "}
                  {history.data.length - 1 === 1 ? "diagnosis" : "diagnoses"}
                </summary>
                <div className="mt-4 flex flex-col gap-6 border-l-2 border-token pl-4">
                  {history.data.slice(1).map((d) => (
                    <DiagnosisView key={d.id} diagnosis={d} muted />
                  ))}
                </div>
              </details>
            )}
          </div>
        ) : (
          <div className="py-6 text-center text-sm text-muted">
            No diagnosis yet.{" "}
            {canDiagnose
              ? "Run one to get a grounded root-cause analysis with cited sources."
              : "An engineer can generate one."}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function DiagnosisView({ diagnosis: d, muted }: { diagnosis: Diagnosis; muted?: boolean }) {
  return (
    <div className={muted ? "opacity-80" : ""}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <ConfidenceBadge value={d.confidence_label} />
        <span className="text-sm text-muted">
          confidence {percent(d.confidence_score)}
          {d.top_relevance != null && ` · top match ${percent(d.top_relevance)}`}
        </span>
        <span className="ml-auto text-xs text-muted">
          {d.provider}/{d.model} · {formatDateTime(d.created_at)}
        </span>
      </div>

      {d.is_uncertain && (
        <div className="mb-3">
          <Alert tone="info">
            This diagnosis is not well grounded in the knowledge base. Upload
            relevant documentation and re-run for a stronger answer.
          </Alert>
        </div>
      )}

      <div className="flex flex-col gap-3 text-sm">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">Root cause</div>
          <p className="mt-1 whitespace-pre-wrap">{d.root_cause}</p>
        </div>
        {d.recommended_fix && (
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">
              Recommended fix
            </div>
            <p className="mt-1 whitespace-pre-wrap">{d.recommended_fix}</p>
          </div>
        )}
        {d.sources.length > 0 && (
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">
              Sources ({d.sources.length})
            </div>
            <ul className="mt-2 flex flex-col gap-2">
              {d.sources.map((s, i) => (
                <li key={i} className="rounded-lg border border-token bg-[var(--surface-2)] px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{s.document_title || "Untitled"}</span>
                    {s.score != null && (
                      <span className="shrink-0 text-xs text-muted">{percent(s.score)}</span>
                    )}
                  </div>
                  {s.excerpt && <p className="mt-1 line-clamp-3 text-xs text-muted">{s.excerpt}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function RawDumps({ crash: c }: { crash: Crash }) {
  const registers = c.register_dump ?? {};
  const hasRegisters = Object.keys(registers).length > 0;
  const stack = c.stack_dump ?? {};
  const hasStack = Object.keys(stack).length > 0;
  if (!hasRegisters && !hasStack) return null;

  return (
    <Card>
      <CardHeader title="Raw dumps" />
      <CardBody>
        <details>
          <summary className="cursor-pointer text-sm text-muted hover:text-brand-600">
            Register &amp; stack dump
          </summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {hasRegisters && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  Registers
                </div>
                <div className="scrollbar-thin overflow-x-auto rounded-lg bg-[var(--surface-2)] p-3 font-mono text-xs">
                  {Object.entries(registers).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4">
                      <span className="text-muted">{k}</span>
                      <span>{String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {hasStack && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  Stack
                </div>
                <pre className="scrollbar-thin max-h-64 overflow-auto rounded-lg bg-[var(--surface-2)] p-3 font-mono text-xs">
                  {JSON.stringify(stack, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </details>
      </CardBody>
    </Card>
  );
}

function TriageModal({ crash: c, onClose }: { crash: Crash; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState(c.status);
  const [severity, setSeverity] = useState(c.severity);
  const [notes, setNotes] = useState(c.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => crashesApi.update(c.id, { status, severity, notes }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["crash", c.id] });
      void queryClient.invalidateQueries({ queryKey: ["crashes"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal
      open
      title="Triage crash"
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
        <div className="grid grid-cols-2 gap-3">
          <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {CRASH_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
          <Select label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)}>
            {CRASH_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
        </div>
        <Textarea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} />
      </div>
    </Modal>
  );
}
