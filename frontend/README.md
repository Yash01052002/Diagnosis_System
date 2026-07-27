# Frontend — Phase 4

React 19 + TypeScript + Vite + Tailwind CSS single-page application.

Planned in Phase 4:

- Auth flows (login, register, forgot/reset password) against `/api/v1/auth`
- Axios client with automatic access-token refresh on 401
- Role-aware routing: `admin`, `engineer`, `viewer`
- Device list/detail, crash history with symbolized stack traces
- Dashboard and analytics charts (Phase 5)
- Dark/light theme, responsive layout

The backend already exposes everything the auth screens need; see
[`../docs/api/curl-examples.md`](../docs/api/curl-examples.md).
