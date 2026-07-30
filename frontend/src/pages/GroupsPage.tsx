import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { groupsApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { GROUP_STATUSES } from "../lib/labels";
import { formatRelative, humanize } from "../lib/format";
import { PageHeader } from "../components/page";
import { Card } from "../components/Card";
import { Select } from "../components/Input";
import { Pagination } from "../components/Pagination";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { FaultBadge, GroupStatusBadge, SeverityBadge } from "../components/badges";
import { EmptyState, ErrorState, LoadingState } from "../components/feedback";

export function GroupsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["groups", { status, page }],
    queryFn: () => groupsApi.list({ status: status || undefined, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Crash groups"
        subtitle="Distinct bugs — every report sharing a signature, collapsed into one."
      />

      <Card className="mb-4 p-3">
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="sm:max-w-[14rem]"
        >
          <option value="">All statuses</option>
          {GROUP_STATUSES.map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </Select>
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
                  <TH>Bug</TH>
                  <TH>Fault</TH>
                  <TH>Severity</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Occurrences</TH>
                  <TH className="text-right">Devices</TH>
                  <TH>Last seen</TH>
                </TR>
              </THead>
              <TBody>
                {query.data.items.map((g) => (
                  <TR key={g.id} onClick={() => navigate(`/groups/${g.id}`)}>
                    <TD>
                      <div className="font-medium">{g.title}</div>
                      {g.top_function && (
                        <div className="font-mono text-xs text-muted">{g.top_function}</div>
                      )}
                    </TD>
                    <TD>
                      <FaultBadge value={g.fault_type} />
                    </TD>
                    <TD>
                      <SeverityBadge value={g.severity} />
                    </TD>
                    <TD>
                      <GroupStatusBadge value={g.status} />
                    </TD>
                    <TD className="text-right font-medium">{g.occurrence_count.toLocaleString()}</TD>
                    <TD className="text-right">{g.device_count.toLocaleString()}</TD>
                    <TD className="text-muted">{formatRelative(g.last_seen_at)}</TD>
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
          <EmptyState title="No crash groups" hint="Groups appear once crashes are symbolized and signed." />
        )}
      </Card>
    </>
  );
}
