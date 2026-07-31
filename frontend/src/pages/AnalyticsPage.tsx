import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { confidenceColor, severityColor } from "../lib/chartColors";
import { formatRelative } from "../lib/format";
import { PageHeader } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { BarChart } from "../components/charts/BarChart";
import { TrendChart } from "../components/charts/TrendChart";
import { ExportButtons } from "./DashboardPage";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { ErrorState, LoadingState } from "../components/feedback";

const RANGES = [7, 30, 90] as const;

export function AnalyticsPage() {
  const [days, setDays] = useState<number>(30);

  const trend = useQuery({
    queryKey: ["analytics-trend", days],
    queryFn: () => analyticsApi.crashTrend(days),
  });
  const faults = useQuery({
    queryKey: ["analytics-faults"],
    queryFn: analyticsApi.faultDistribution,
  });
  const firmware = useQuery({
    queryKey: ["analytics-firmware"],
    queryFn: () => analyticsApi.firmwareComparison(10),
  });
  const reliability = useQuery({
    queryKey: ["analytics-reliability"],
    queryFn: () => analyticsApi.deviceReliability(10),
  });
  const confidence = useQuery({
    queryKey: ["analytics-confidence"],
    queryFn: analyticsApi.confidenceDistribution,
  });

  return (
    <>
      <PageHeader
        title="Analytics"
        subtitle="Trends, distributions and reliability across the fleet."
        actions={<ExportButtons />}
      />

      <Card className="mb-6">
        <CardHeader
          title="Crash trend"
          actions={
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <button
                  key={r}
                  onClick={() => setDays(r)}
                  className={
                    "rounded-md px-2.5 py-1 text-sm " +
                    (days === r ? "bg-brand-600 text-white" : "text-muted hover:surface-2")
                  }
                >
                  {r}d
                </button>
              ))}
            </div>
          }
        />
        <CardBody>
          {trend.isLoading ? (
            <LoadingState label="Loading trend…" />
          ) : trend.isError ? (
            <ErrorState message={errorMessage(trend.error)} onRetry={() => trend.refetch()} />
          ) : trend.data ? (
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
          ) : null}
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Fault distribution" />
          <CardBody>
            {faults.data ? (
              <BarChart
                data={faults.data.by_fault_type.map((f) => ({ label: f.key, value: f.count }))}
              />
            ) : (
              <LoadingState label="Loading…" />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Severity & status" />
          <CardBody className="flex flex-col gap-5">
            {faults.data && (
              <>
                <div>
                  <div className="mb-2 text-xs uppercase tracking-wide text-muted">Severity</div>
                  <BarChart
                    data={faults.data.by_severity.map((s) => ({
                      label: s.key,
                      value: s.count,
                      color: severityColor(s.key),
                    }))}
                  />
                </div>
                <div>
                  <div className="mb-2 text-xs uppercase tracking-wide text-muted">
                    Triage status
                  </div>
                  <BarChart
                    data={faults.data.by_status.map((s) => ({ label: s.key, value: s.count }))}
                  />
                </div>
              </>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Crashes by firmware" />
          <CardBody>
            {firmware.data ? (
              <BarChart
                humanizeLabels={false}
                data={firmware.data.firmwares.map((f) => ({
                  label: f.firmware_version,
                  value: f.crashes,
                  sub: `${f.devices} device(s)`,
                }))}
              />
            ) : (
              <LoadingState label="Loading…" />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="AI confidence"
            subtitle={
              confidence.data
                ? `${confidence.data.total} diagnoses · ${confidence.data.uncertain} uncertain`
                : undefined
            }
          />
          <CardBody>
            {confidence.data ? (
              confidence.data.total === 0 ? (
                <p className="py-8 text-center text-sm text-muted">No diagnoses yet.</p>
              ) : (
                <BarChart
                  humanizeLabels={false}
                  data={confidence.data.by_label.map((c) => ({
                    label: c.key.charAt(0).toUpperCase() + c.key.slice(1),
                    value: c.count,
                    color: confidenceColor(c.key),
                  }))}
                />
              )
            ) : (
              <LoadingState label="Loading…" />
            )}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader
          title="Device reliability"
          subtitle={
            reliability.data?.fleet_mtbf_hours != null
              ? `Fleet MTBF: ${reliability.data.fleet_mtbf_hours.toFixed(1)} h`
              : "Mean time between failures per device"
          }
        />
        <CardBody className="p-0">
          {reliability.isLoading ? (
            <LoadingState label="Loading…" />
          ) : reliability.data && reliability.data.devices.length > 0 ? (
            <Table>
              <THead>
                <TR>
                  <TH>Device</TH>
                  <TH>Model</TH>
                  <TH className="text-right">Crashes</TH>
                  <TH className="text-right">MTBF (h)</TH>
                  <TH>Last crash</TH>
                </TR>
              </THead>
              <TBody>
                {reliability.data.devices.map((d) => (
                  <TR key={d.device_id}>
                    <TD className="font-medium">{d.device_identifier}</TD>
                    <TD className="text-muted">{d.hardware_model}</TD>
                    <TD className="text-right tabular-nums">{d.crashes}</TD>
                    <TD className="text-right tabular-nums">
                      {d.mtbf_hours != null ? d.mtbf_hours.toFixed(1) : "—"}
                    </TD>
                    <TD className="text-muted">{formatRelative(d.last_crash_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : (
            <p className="py-8 text-center text-sm text-muted">No crash data yet.</p>
          )}
        </CardBody>
      </Card>
    </>
  );
}
