# Phase 5 — Dashboard, Analytics, Export & Notifications

## Objectives

1. Turn the raw crash record into **decisions**: a dashboard that answers "is
   the fleet healthy, and what is hurting it most" in one screen.
2. Analytics that stand on their own definitions — a health score, a crash
   trend, mean-time-between-failures — computed in one place, not re-derived per
   caller.
3. **Export** the underlying data (CSV) and a shareable **report** (PDF) so the
   numbers leave the app.
4. **Alerting**: a critical crash should reach a human without anyone watching a
   list, with a threshold and recipients an admin controls.
5. Keep everything **portable and offline-testable** — the same SQLite-backed
   test suite, no new external services, the PDF dependency imported lazily.

## Analytics

```
 crash_reports / crash_groups / devices / ai_diagnoses / documents
        │  GROUP BY / COUNT (AnalyticsRepository)
        ▼
 AnalyticsRepository        raw aggregates, one query each
        │
        ▼
 AnalyticsService           derived figures: health score, gap-filled
        │                   trend, MTBF — the definitions live here
        ▼
 /analytics/*               summary · crash-trend · fault-distribution ·
                            firmware-comparison · device-reliability ·
                            confidence-distribution   (viewer)
```

The split is deliberate: the **repository** only knows SQL aggregates, the
**service** owns every derived definition, so "what is the health score" or "how
is MTBF computed" has exactly one answer in the codebase.

Derived figures worth naming:

- **Device health score** — the share of devices with *no open critical crash*,
  as a 0–100 percentage. A fleet where every device has a live critical bug
  scores 0; one with none scores 100.
- **Crash trend** — daily counts (with a critical split) over a window, and
  **gap-filled**: a day with no crashes is a real `0`, not a missing point, so
  the line never lies by omission.
- **MTBF** — mean time between failures. With *N* crashes there are *N−1*
  intervals, so a single crash yields `null` rather than a fabricated number;
  the figure is `span / (N−1)` per device, and `span / (total−1)` fleet-wide.

### SQL portability — the one sharp edge

Bucketing a timestamp to a day is the only query that differs by database:
SQLite spells it `strftime('%Y-%m-%d', …)`, PostgreSQL `to_char(…, 'YYYY-MM-DD')`.
`AnalyticsRepository._day_expr` picks the right one from the active dialect, so
the trend query is a single grouped `SELECT` on both, and the tests (SQLite)
exercise the same code path production (PostgreSQL) runs. Everything else is
standard `COUNT`/`GROUP BY`/`AVG`.

## Export

Two endpoints, both viewer-gated, both returning a file with a
`Content-Disposition` attachment name:

- **`/export/crashes.csv`** — the crash history, filtered exactly like the list
  view, rendered with the stdlib `csv` module (correct quoting, no dependency).
  Capped at the most recent 10,000 matching rows so the response is bounded.
- **`/export/analytics.pdf`** — a one-page report (overview, fault
  distribution, top root causes, firmware comparison, reliability) built with
  **ReportLab**, imported *inside the builder* so the dependency is only needed
  when a PDF is actually requested — the rest of the platform, and its test
  suite, never import it.

## Notifications & alerts

Two responsibilities behind one service:

**The inbox.** A `Notification` is one message to one user with its own
`read_at`, so read state is per-recipient. The endpoints are the obvious set —
list, unread-count (indexed, cheap, for the bell badge), mark-one-read,
mark-all-read.

**Alert escalation.** On ingest, if a crash meets the configured severity
threshold, one notification is created per eligible recipient (users holding an
alert role), and — if enabled — an email is sent to each. Three properties are
enforced in code:

- **Best-effort, never fatal.** The crash is already committed before alerting
  runs; the whole fan-out is wrapped so a failure is logged and rolled back, and
  ingestion still returns success. A crash report is evidence — nothing in
  alerting may lose it.
- **Threshold is a total order.** Severities are ranked
  (`low < medium < high < critical`) so "at or above `min_severity`" is
  unambiguous. A `medium` crash under a `critical` threshold raises nothing.
- **Policy lives in the database.** `AlertSettings` is a single row an admin
  edits at runtime (threshold, recipients, email toggle); until saved, the
  service returns a transient default built from config, so a fresh install
  behaves sensibly with no data-migration step.

```
 POST /crashes ─▶ CrashService.ingest
                     │  (store, symbolize, group — all committed)
                     ▼
                  NotificationService.alert_for_crash   ← best-effort
                     │  severity ≥ threshold?
                     ▼
                  one Notification per recipient  (+ optional email)
                     │
              bell badge ◀── /notifications/unread-count (polled)
```

The alert path is wired into `CrashService` as an **optional** collaborator,
exactly like symbolization — so the ingestion logic can still be tested with no
alerting stack in scope.

## Data model additions

```
┌───────────────────────────┐        ┌──────────────────────────┐
│       notifications       │        │      alert_settings      │
├───────────────────────────┤        ├──────────────────────────┤
│ user_id   FK CASCADE  IDX │        │ enabled                  │
│ level (info/warn/critical)│        │ email_enabled            │
│ category                  │        │ min_severity             │
│ title, body               │        │ recipient_roles   JSONB  │
│ resource_type/_id         │ ← deep │ notify_on_regression     │
│ read_at              IDX  │   link │ (single row; config      │
│ meta               JSONB  │        │  supplies the default)   │
└───────────────────────────┘        └──────────────────────────┘
   (user_id, read_at) and (user_id, created_at) composite indexes
   keep the inbox list and the unread badge cheap.
```

Migration `0005`. Analytics adds **no** tables — it reads what Phases 2–3
already store.

## API surface

| Method | Path | Role | Purpose |
|---|---|---|---|
| `GET` | `/analytics/summary` | viewer | Dashboard totals, health score, distributions, top bugs |
| `GET` | `/analytics/crash-trend` | viewer | Daily counts (+ critical) over a window |
| `GET` | `/analytics/fault-distribution` | viewer | Counts by fault / severity / status |
| `GET` | `/analytics/firmware-comparison` | viewer | Crashes and devices per firmware |
| `GET` | `/analytics/device-reliability` | viewer | Per-device + fleet MTBF |
| `GET` | `/analytics/confidence-distribution` | viewer | AI diagnosis confidence spread |
| `GET` | `/export/crashes.csv` | viewer | Crash history as CSV |
| `GET` | `/export/analytics.pdf` | viewer | One-page analytics report |
| `GET` | `/notifications` | any user | Your notifications |
| `GET` | `/notifications/unread-count` | any user | Badge count |
| `POST` | `/notifications/{id}/read` | any user | Mark one read |
| `POST` | `/notifications/read-all` | any user | Mark all read |
| `GET` | `/notifications/settings` | admin | Read the alert policy |
| `PATCH` | `/notifications/settings` | admin | Change threshold / recipients / email |

## Frontend

- **Dashboard** — stat tiles (online devices, health score, crashes today,
  critical open, AI diagnoses, KB docs), the crash-trend chart, fault/severity
  distributions, and the top-root-causes list, plus the CSV/PDF export buttons.
- **Analytics** — the same trend with a 7/30/90-day selector, fault/severity/
  status distributions, firmware comparison, a device-reliability table with
  MTBF, and the AI confidence distribution.
- **Notifications** — a bell in the top bar with a live unread badge and a
  recent-items dropdown that deep-links a crash alert straight to the crash; a
  full inbox page; and, for admins, the alert-settings editor.

### Charts, built to a method

The charts are hand-rolled (no charting dependency) against the project's
data-viz method, which makes the visual choices rules rather than taste:

- **One shared y-axis, never dual-axis.** The trend's "all crashes" and
  "critical" series share a scale and a legend.
- **Colour by the job.** Magnitude bars use a single sequential hue (identity is
  in the row label); severity and confidence use the **reserved status hues**,
  always beside a text label, never colour alone.
- **Theme-aware tokens.** Chart colours are CSS variables with validated light
  and dark values (the categorical pair was run through the palette validator —
  CVD ΔE 23.8), so a chart is legible in both themes and colour-blind-safe.
- **A hover layer by default** — a crosshair tooltip on the trend, per-bar
  titles on the distributions.

## Testing

- **Backend** — analytics integration tests assert the health score, gap-filled
  trend, MTBF arithmetic and distributions against seeded data; export tests
  assert the CSV header/rows and the `%PDF-` magic; notification tests drive a
  **real critical crash through ingestion** and assert the right users are
  alerted (and that a below-threshold crash alerts no one), plus the inbox and
  admin-only settings. 19 new tests (404 total); ruff + mypy clean; migration
  `0005` column-parity verified against the models.
- **Frontend** — chart and colour-mapping unit tests (26 total); type-check,
  ESLint and the production build clean.
- **Live smoke** — the end-to-end script covers every Phase 5 endpoint against a
  running server (90 checks), including the alert notifications raised by the
  critical crashes it submits earlier in the run.
