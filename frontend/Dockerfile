# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1: deps -- node_modules only.
#
# Same caching trick as the backend: package.json + lockfile alone, install,
# THEN source. Editing a component must not re-run npm ci.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app

# `package*.json` matches package.json and package-lock.json if it exists. The
# lockfile is what makes builds reproducible -- commit it.
COPY package*.json ./

# `npm ci` (not `npm install`): it installs exactly the lockfile, fails if
# package.json and the lockfile disagree, and never mutates the lockfile.
# The `|| npm install` fallback only exists so a fresh clone without a lockfile
# still builds; once package-lock.json is committed, ci always wins.
RUN --mount=type=cache,target=/root/.npm \
    npm ci || npm install

# ---------------------------------------------------------------------------
# Stage 2: dev -- the Vite dev server, used only by docker-compose.yml.
#
# Compose targets this stage explicitly (`target: dev`) and bind-mounts the
# source over /app, so edits on the host trigger HMR in the container. No
# source is COPYed here on purpose: whatever we baked in would be shadowed by
# the mount anyway.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS dev
WORKDIR /app
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
COPY package*.json ./
EXPOSE 5173
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------------------
# Stage 3: build -- compile to static assets.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 4: runtime -- nginx serving /dist. No node, no npm, no source.
#
# This is the payoff of multi-stage: the final image is ~50MB of nginx plus a
# few hundred KB of JS. The 400MB of node_modules that produced it never ship,
# so there is nothing there to CVE-scan or exploit.
#
# nginx-unprivileged runs as a non-root user out of the box and listens on 8080
# (ports below 1024 need CAP_NET_BIND_SERVICE). Stock `nginx` starts its master
# process as root; this variant does not.
# ---------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:8080/healthz || exit 1
