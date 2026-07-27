# Nginx — Phase 6

Reverse proxy for the production stack:

- TLS termination and HTTP→HTTPS redirect
- `/api` → backend, `/` → frontend static build
- Rate limiting on `/api/v1/auth/*`
- gzip/brotli, cache headers for static assets
- `X-Forwarded-For` forwarding (the backend already reads it for audit entries)
