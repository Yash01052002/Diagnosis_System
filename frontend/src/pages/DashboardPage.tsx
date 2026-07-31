import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi, exportApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { severityColor } from "../lib/chartColors";
import { PageHeader } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { StatTile } from "../components/charts/StatTile";
import { BarChart } from "../components/charts/BarChart";
import { TrendChart } from "../components/charts/TrendChart";
import { FaultBadge, GroupStatusBadge, SeverityBadge } from "../components/badges";
import { ErrorState, LoadingState } from "../components/feedback";

export function DashboardPage() {
  const summary = useQuery({ queryKey: ["analytics-summary"], queryFn: analyticsApi.summary });
  const trend = useQuery({
    queryKey: ["analytics-trend", 30],
    queryFn: () => analyticsApi.crashTrend(30),
  });

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Fleet health and crash activity at a glance."
        actions={<ExportButtons />}
      />

      {summary.isLoading ? (
        <LoadingState />
      ) : summary.isError || !summary.data ? (
        <ErrorState message={errorMessage(summary.error)} onRetry={() => summary.refetch()} />
      ) : (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile
              label="Devices online"
              value={summary.data.devices.online}
              hint={`${summary.data.devices.total} total`}
              to="/devices"
            />
            <StatTile
              label="Health score"
              value={`${summary.data.device_health_score}%`}
              tone={summary.data.device_health_score < 50 ? "danger" : "success"}
              hint="devices without open critical"
            />
            <StatTile
              label="Crashes today"
              value={summary.data.crashes.today}
              hint={`${summary.data.crashes.last_7d} in last 7 days`}
              to="/crashes"
            />
            <StatTile
              label="Critical open"
              value={summary.data.crashes.critical_open}
              tone={summary.data.crashes.critical_open > 0 ? "danger" : "default"}
              hint={`${summary.data.crashes.open} open total`}
              to="/crashes?severity=critical"
            />
          </div>

          <Card>
            <CardHeader
              title="Crash trend"
              subtitle="Last 30 days"
              actions={
                <Link to="/analytics" className="text-sm text-brand-600 hover:underline">
                  More analytics →
                </Link>
              }
            />
            <CardBody>
              {trend.data ? (
                <TrendChart
                  labels={trend.data.points.map((p) => p.date)}
                  series={[
                    {
                      name: "All crashes",
                      color: "var(--chart-series-1)",
                      values: trend.data.points.map((p) => p.count),
                    },
                    {
                      name: "Critical",
                      color: "var(--chart-critical)",
                      values: trend.data.points.map((p) => p.critical),
                    },
                  ]}
                />
              ) : (
                <LoadingState label="Loading trend…" />
              )}
            </CardBody>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="By fault type" />
              <CardBody>
                <BarChart
                  data={summary.data.by_fault_type.map((f) => ({ label: f.key, value: f.count }))}
                />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="By severity" />
              <CardBody>
                <BarChart
                  data={summary.data.by_severity.map((s) => ({
                    label: s.key,
                    value: s.count,
                    color: severityColor(s.key),
                  }))}
                />
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Top root causes"
              subtitle="The most frequent bugs, by occurrence"
              actions={
                <Link to="/groups" className="text-sm text-brand-600 hover:underline">
                  All groups →
                </Link>
              }
            />
            <CardBody className="p-0">
              {summary.data.top_root_causes.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted">No crash groups yet.</p>
              ) : (
                <ul className="divide-y divide-[color:var(--border)]">
                  {summary.data.top_root_causes.map((rc) => (
                    <li key={rc.id}>
                      <Link
                        to={`/groups/${rc.id}`}
                        className="flex items-center gap-3 px-5 py-3 hover:surface-2"
                      >
                        <span className="w-10 text-right text-lg font-semibold tabular-nums">
                          {rc.occurrence_count}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{rc.title}</span>
                          {rc.top_function && (
                            <span className="block truncate font-mono text-xs text-muted">
                              {rc.top_function}
                            </span>
                          )}
                        </span>
                        <FaultBadge value={rc.fault_type} />
                        <SeverityBadge value={rc.severity} />
                        <GroupStatusBadge value={rc.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatTile label="AI diagnoses" value={summary.data.diagnoses_total} to="/crashes" />
            <StatTile
              label="KB documents"
              value={summary.data.documents_total}
              to="/knowledge-base"
            />
            <StatTile label="Active devices" value={summary.data.devices.active} />
            <StatTile label="Total crashes" value={summary.data.crashes.total} />
          </div>
        </div>
      )}
    </>
  );
}

export function ExportButtons() {
  const [busy, setBusy] = useState<string | null>(null);

  async function run(kind: "csv" | "pdf") {
    setBusy(kind);
    try {
      await exportApi.download(
        kind === "csv" ? exportApi.crashesCsvUrl : exportApi.analyticsPdfUrl,
      );
    } catch {
      // errors surface via the browser; keep the dashboard quiet
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex gap-2">
      <Button variant="secondary" size="sm" loading={busy === "csv"} onClick={() => run("csv")}>
        Export CSV
      </Button>
      <Button variant="secondary" size="sm" loading={busy === "pdf"} onClick={() => run("pdf")}>
        Export PDF
      </Button>
    </div>
  );
}
