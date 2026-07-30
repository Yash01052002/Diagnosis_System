# Phase 4 — Frontend Application

## Objectives

1. A single-page application over the entire Phase 1–3 API: authentication,
   devices, crashes with symbolized stack traces, crash groups, AI diagnosis,
   and the knowledge base.
2. **Role-aware** throughout — what a `viewer`, `engineer` or `admin` can see
   and do is enforced in the routes and the controls, mirroring the backend.
3. A session that survives a reload and refreshes itself transparently, so an
   expiring access token is never something the user notices.
4. Dark/light theme, responsive from phone to desktop, and honest loading /
   empty / error states on every data view.
5. Ship as a static bundle behind nginx that also proxies the API, so the SPA
   and API share an origin — no CORS, and the same relative URLs work in dev
   and prod.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Build/dev | Vite 6 | Fast HMR; the dev server proxies `/api` to the backend |
| UI | React 19 + TypeScript (strict) | Types mirror the Pydantic schemas |
| Styling | Tailwind CSS v4 | Semantic CSS-variable tokens drive both themes |
| Server state | TanStack Query v5 | Caching, refetch, mutation invalidation |
| Routing | React Router v7 | Nested layout + route guards |
| HTTP | Axios | One place for auth headers and refresh |
| Tests | Vitest + Testing Library | Unit + component, jsdom |

React Router and TanStack Query own two different kinds of state — *where you
are* and *what the server knows* — and keeping them separate is what keeps the
pages small. There is no client-side store beyond auth; every screen is a query.

## Layering

```
 pages/            screens — compose components, own local UI state
   │  useQuery / useMutation
   ▼
 api/endpoints     typed thin wrappers over each REST route
   │
   ▼
 api/client        axios instance: auth header + transparent refresh
   │
   ▼
 api/tokenStore    the tokens, outside React so interceptors can reach them
```

`api/types.ts` is a hand-maintained mirror of `app/schemas`. It is deliberately
close to the server types so that a contract change shows up here as a
type error rather than a runtime surprise.

## Authentication & the refresh flow

The heart of the client is `api/client.ts`. Tokens live in `tokenStore` (backed
by `localStorage`) rather than React state, because the Axios interceptors that
read and rotate them run with no component in scope.

- **Request** — every call gets `Authorization: Bearer <access>`.
- **Response 401** — the access token has almost certainly expired. The
  interceptor calls `/auth/refresh` with the rotating refresh token, stores the
  new pair, and **replays the original request**.
- **Single-flight** — a burst of parallel requests that all 401 shares *one*
  refresh call. The refresh token is single-use on the server; spending it N
  times in parallel would invalidate it. `refreshing` holds the in-flight
  promise so everyone awaits the same rotation.
- **Give up cleanly** — if the refresh itself fails, tokens are cleared and
  `tokenStore` notifies its listeners; `AuthProvider` drops the user and the
  router sends them to `/login`. A refresh call is made through a *separate*
  axios instance so it can never recurse through the interceptor.

On first load, `AuthProvider` hydrates the session: if tokens are present it
calls `/auth/me`; a failure just means "logged out".

## Role-aware access

`RequireAuth` gates the authenticated shell; `RequireRole` gates individual
routes (e.g. `/users` is admin-only, bouncing others to `/403`). The same
`hasRole` helper hides controls a role cannot use — an engineer never sees a
"Delete" button that the API would 403 anyway. Admins pass every check, exactly
as `require_roles` does on the server, so the two never disagree.

Buttons are hidden *and* the API enforces — the UI gate is for clarity, the
server gate is the security boundary.

## Screens

| Route | Screen | Notes |
|---|---|---|
| `/login`, `/register` | Auth | Register auto-signs-in with the new viewer account |
| `/forgot-password`, `/reset-password` | Password reset | Token from the email link, or pasted |
| `/devices` | Device list | Search + status filter, register (engineer) |
| `/devices/:id` | Device detail | Stats, API keys (create/revoke), edit, delete, recent crashes |
| `/crashes` | Crash list | Fault/severity/status filters, deep-linked device filter |
| `/crashes/:id` | Crash detail | **Symbolized stack trace + AI diagnosis panel** |
| `/groups`, `/groups/:id` | Crash groups | One row per bug; occurrences; triage |
| `/knowledge-base` | Knowledge base | Stats, semantic search, add/upload docs, delete |
| `/users` | User admin | Admin only — roles, activation, deletion |
| `/profile` | Profile | Update details, change password, sign out everywhere |

### The crash detail page

This is where Phases 2.5 and 3 surface to a human:

- The **symbolized stack trace** renders innermost-first, each frame showing
  `function+offset at file:line`, with unresolved frames shown as raw addresses
  and a "resolved N/M frames" summary — a direct view of the Phase 2.5 output.
- The **AI diagnosis panel** shows the latest diagnosis (root cause, recommended
  fix, a confidence badge, and the **cited sources** with match scores) and
  keeps a foldable history of earlier runs. An engineer runs or re-runs a
  diagnosis inline. When the backend returns an *uncertain* result, the panel
  says so plainly and points at the knowledge base — the anti-hallucination
  contract from Phase 3, made visible rather than hidden behind a number.

## Theming

Two value sets over one set of semantic CSS variables (`--bg`, `--surface`,
`--text`, …); components never hard-code a light or dark colour. A pre-paint
script in `index.html` applies the saved theme before first render to avoid a
flash, and `useTheme` toggles the `dark` class on `<html>` and persists the
choice.

## Build & serve

`npm run build` type-checks then bundles to `dist/`. The multi-stage
`Dockerfile` builds with Node and serves the static files from nginx, which:

- falls back to `index.html` so a hard refresh on `/crashes/123` still loads the
  app (client-side routing), and
- reverse-proxies `/api` and `/health` to the backend, resolving the upstream at
  request time via Docker DNS so nginx starts even before the backend is up.

The `frontend` service in `docker-compose.yml` puts it on
`http://localhost:${FRONTEND_PORT:-3000}`.

## Tests

Vitest + Testing Library, run offline in jsdom:

- **Formatting** — hex/relative-time/percent/humanize helpers.
- **Password policy** — the client mirror of the server rules.
- **Token store** — persistence and the cleared-session notification.
- **API error unwrapping** — the `{ error: {...} }` envelope → human message.
- **Component render** — the login screen renders and navigates to register.

The refresh flow's security properties (single-flight, replay, give-up) live in
`api/client.ts` and are exercised end to end whenever the app runs against a
real backend; the unit tests cover the pure pieces around them.
