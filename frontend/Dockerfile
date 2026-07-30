# syntax=docker/dockerfile:1.7
# Multi-stage build: compile the SPA with Node, then serve the static bundle
# from a tiny nginx image. The runtime image ships no Node and no source.

FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies against the lockfile first so this layer is cached until
# the manifest changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# VITE_API_BASE_URL defaults to /api/v1 (same-origin behind nginx). Override at
# build time only for an API on a different origin.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build


FROM nginx:1.27-alpine AS runtime

# SPA routing + API reverse proxy.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1
