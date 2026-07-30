# Frontend — BlackBox Web Application

React 19 + TypeScript + Vite + Tailwind CSS v4 single-page application for the
BlackBox crash-diagnosis platform. TanStack Query for server state, React Router
for routing, Axios with automatic access-token refresh.

## Quick start

```bash
cp .env.example .env          # optional; defaults work with the dev proxy
npm install
npm run dev                   # http://localhost:5173, proxies /api to :8000
```

The dev server proxies `/api` to the backend (default `http://localhost:8000`),
so the SPA and API share an origin with no CORS setup. Point it elsewhere with
`VITE_PROXY_TARGET`.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server with HMR and the API proxy |
| `npm run build` | Type-check (`tsc -b`) and produce a production bundle in `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run typecheck` | Type-check without emitting |
| `npm run lint` | ESLint over the project |
| `npm run test` | Vitest unit/component suite |

## Structure

```
src/
├── api/            Axios client (token refresh), typed endpoints, TS types
├── auth/           AuthProvider, context and useAuth hook
├── app/            App router, route guards, the authenticated app shell
├── components/     Reusable UI: Button, Input, Card, Table, Modal, badges…
├── lib/            Formatting, labels/tones, theme, small hooks
├── pages/          One file per screen
└── test/           Vitest setup and helpers
```

## How it talks to the API

- **Auth.** On load, if tokens are in `localStorage` the app calls `/auth/me` to
  restore the session. `login` stores the returned access + refresh tokens.
- **Transparent refresh.** A `401` triggers a single-flighted refresh via the
  rotating refresh token, then the original request is replayed. If the refresh
  fails, tokens are cleared and the router sends the user to `/login`.
- **Errors.** Every failure is unwrapped from the backend's `{ error: {...} }`
  envelope into a human message shown inline.

## Roles

Routes and controls are role-aware (`admin` > `engineer` > `viewer`):

- **viewer** — read devices, crashes, groups and the knowledge base.
- **engineer** — register/edit devices and API keys, triage crashes, run AI
  diagnoses, manage knowledge-base documents, semantic search.
- **admin** — everything, plus user administration and deletions.

## Production

`Dockerfile` builds the bundle with Node and serves it from nginx, which also
reverse-proxies `/api` to the backend (see `nginx.conf`). The `frontend` service
in the repo's `docker-compose.yml` wires it up; browse to
`http://localhost:${FRONTEND_PORT:-3000}`.
