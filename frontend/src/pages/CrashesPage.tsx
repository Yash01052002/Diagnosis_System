import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { crashesApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { CRASH_SEVERITIES, CRASH_STATUSES, FAULT_TYPES } from "../lib/labels";
import { formatDateTime, humanize, toHex } from "../lib/format";
import { PageHeader } from "../components/page";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Input, Select } from "../components/Input";
import { Pagination } from "../components/Pagination";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { CrashStatusBadge, FaultBadge, SeverityBadge } from "../components/badges";
import { EmptyState, ErrorState, LoadingState } from "../components/feedback";

export function CrashesPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const device = searchParams.get("device") ?? "";

  const [faultType, setFaultType] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["crashes", { device, faultType, severity, status, page }],
    queryFn: () =>
      crashesApi.list({
        device: device || undefined,
        fault_type: faultType || undefined,
        severity: severity || undefined,
        status: status || undefined,
        page,
        page_size: 20,
      }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Crashes"
        subtitle="Every crash report received, newest first."
        actions={
          device && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                searchParams.delete("device");
                setSearchParams(searchParams);
                setPage(1);
              }}
            >
              Clear device filter
            </Button>
          )
        }
      />

      <Card className="mb-4 p-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <Select
            value={faultType}
            onChange={(e) => {
              setFaultType(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All fault types</option>
            {FAULT_TYPES.map((f) => (
              <option key={f} value={f}>
                {humanize(f)}
              </option>
            ))}
          </Select>
          <Select
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All severities</option>
            {CRASH_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">All statuses</option>
            {CRASH_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
          {device && (
            <Input value={device} readOnly aria-label="Device filter" className="text-muted" />
          )}
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
                  <TH>When</TH>
                  <TH>Device</TH>
                  <TH>Fault</TH>
                  <TH>Function</TH>
                  <TH>Task</TH>
                  <TH>Severity</TH>
                  <TH>Status</TH>
                </TR>
              </THead>
              <TBody>
                {query.data.items.map((c) => (
                  <TR key={c.id} onClick={() => navigate(`/crashes/${c.id}`)}>
                    <TD>{formatDateTime(c.occurred_at)}</TD>
                    <TD className="font-medium">{c.device.device_id}</TD>
                    <TD>
                      <FaultBadge value={c.fault_type} />
                    </TD>
                    <TD className="font-mono text-xs">{c.top_function || toHex(c.program_counter)}</TD>
                    <TD>{c.task_name || "—"}</TD>
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
          <EmptyState title="No crashes found" hint="Nothing matches these filters." />
        )}
      </Card>
    </>
  );
}
