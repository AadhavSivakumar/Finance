# Docker, end to end

A walkthrough of Docker using this repository as the worked example. Every
command here runs against the actual files in this project, and every file
referenced is one you can open.

Read it in order the first time. After that it works as a reference.

---

## Contents

1. [The mental model](#1-the-mental-model)
2. [Images, layers and the build cache](#2-images-layers-and-the-build-cache)
3. [Reading our Dockerfiles](#3-reading-our-dockerfiles)
4. [Running a single container](#4-running-a-single-container)
5. [Compose: the whole stack](#5-compose-the-whole-stack)
6. [The development loop](#6-the-development-loop)
7. [Data: volumes vs bind mounts](#7-data-volumes-vs-bind-mounts)
8. [Networking](#8-networking)
9. [Configuration and secrets](#9-configuration-and-secrets)
10. [Healthchecks and startup order](#10-healthchecks-and-startup-order)
11. [Migrations](#11-migrations)
12. [Building for production](#12-building-for-production)
13. [Registries](#13-registries)
14. [Deploying to a VPS](#14-deploying-to-a-vps)
15. [Operating it](#15-operating-it)
16. [Debugging cheatsheet](#16-debugging-cheatsheet)
17. [Common mistakes](#17-common-mistakes)

---

## 1. The mental model

The single most useful idea: **a container is a process, not a machine.**

A virtual machine boots its own kernel and runs a full operating system. A
container is an ordinary Linux process on *your* kernel, started with a few
extra flags that lie to it about what it can see:

| Kernel feature | What it does |
|---|---|
| **namespaces** | The process sees its own filesystem root, its own PID 1, its own network interfaces, its own hostname. |
| **cgroups** | Caps how much CPU and memory it can use. |
| **union filesystem** | Assembles its root filesystem from stacked read-only layers plus one writable layer on top. |

Three consequences follow, and most Docker confusion dissolves once they click:

- **There is no "inside the VM" to log into.** `docker exec` starts a *second*
  process in the same namespaces. When the main process exits, the container is
  over — there is nothing left running to attach to.
- **The container shares your kernel.** Which is why a Linux container cannot
  run on Windows without a Linux VM underneath, and why "root inside the
  container" is uid 0 on the host. Containers isolate; they do not, on their
  own, secure.
- **The writable layer dies with the container.** Anything written that is not
  on a volume is gone on `docker rm`. This is a feature — it is what makes
  containers reproducible — but it means state must be deliberately placed.

Four nouns you need:

| Noun | What it is |
|---|---|
| **Image** | A stack of read-only layers plus metadata (default command, env, exposed ports). A build artifact. Immutable. |
| **Container** | A running (or stopped) instance of an image, with a writable layer on top. |
| **Volume** | Storage that lives outside any container's lifecycle. |
| **Registry** | Where images are stored and shared (Docker Hub, GHCR, ECR). |

The relationship is exactly class → instance. One image, many containers.

---

## 2. Images, layers and the build cache

Each instruction in a Dockerfile produces a layer: a diff of the filesystem
against the layer below.

```
┌─────────────────────────────┐
│ writable layer (container)  │  ← dies with the container
├─────────────────────────────┤
│ COPY . .                    │ ┐
│ RUN pip install -r req.txt  │ │ image layers,
│ COPY requirements.txt .     │ │ read-only and cached
│ FROM python:3.12-slim       │ ┘
└─────────────────────────────┘
```

Two properties do most of the work:

**Layers are append-only.** You cannot shrink an image by deleting a file in a
later layer — the file still exists in the earlier one, and the delete adds
*another* layer recording the removal. This is why `backend/Dockerfile` has:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
```

All in one `RUN`. Split across three, the apt cache would be permanently baked
into the image.

**Layers are cached by content.** Docker reuses a layer if the instruction and
the files it touches are unchanged. Once one layer misses, every layer after it
rebuilds. That single rule dictates instruction order:

```dockerfile
COPY requirements.txt .          # changes rarely
RUN pip install -r requirements.txt
COPY . .                         # changes constantly
```

Reverse those and every edit to `main.py` reinstalls every Python package.
With them in this order, dependency installs are near-instant on rebuilds.

### The build context

`docker build ./backend` first tarballs `./backend` and ships it to the daemon
— *before any instruction runs*. That is the **build context**, and
`.dockerignore` controls what goes into it.

This matters for two reasons: a fat context (a `node_modules`, a `.git`,
a dataset) slows every single build, and `COPY . .` will happily bake a stray
`.env` into a layer that anyone who pulls the image can extract. Our
`.dockerignore` files exclude both.

### Multi-stage builds

A stage whose output you never `COPY --from` never ships. `frontend/Dockerfile`
uses four stages so the final image is nginx plus a few hundred KB of compiled
JS — the ~400 MB of `node_modules` that produced it stays in the build stage.

```
deps ──→ dev      (Vite dev server; used only by docker-compose.yml)
  └────→ build ──→ runtime   (nginx + dist/)
```

Same idea in `backend/Dockerfile`: `builder` has gcc and headers, `runtime`
has neither.

Verify it yourself — these are the actual measured sizes for this repo:

```
finance-web:latest       345MB     ← dev stage (node + node_modules + Vite)
local/finance-web:test    74.5MB   ← runtime stage (nginx + dist/)
```

```bash
docker images | grep finance
docker history finance-web:latest      # find the fat layer
```

### A BuildKit caveat

The `# syntax=` line and `--mount=type=cache` require **BuildKit**.
`docker compose build` enables it automatically. Plain `docker build` may fall
back to the legacy builder and fail with:

```
the --mount option requires BuildKit
```

and `DOCKER_BUILDKIT=1` alone is not enough if the buildx plugin is missing
(`BuildKit is enabled but the buildx component is missing or broken`). Either
use `docker compose build`, or install the plugin:

```bash
sudo apt install docker-buildx
```

---

## 3. Reading our Dockerfiles

Both files are commented line by line — open them alongside this section.
The instructions worth knowing:

| Instruction | Notes |
|---|---|
| `FROM` | Base image. Pin the minor version. Each `FROM` starts a new stage. |
| `WORKDIR` | Sets the directory *and creates it*. Use it instead of `RUN cd`, which does not persist. |
| `COPY` | Host → image. `--from=stage` copies between stages; `--chown` avoids a duplicate layer. |
| `ADD` | Like COPY but also fetches URLs and auto-extracts tarballs. Prefer COPY; ADD's magic surprises people. |
| `RUN` | Executes at **build** time, result becomes a layer. |
| `CMD` | Default **arguments**, overridable by `docker run <image> other args`. |
| `ENTRYPOINT` | The **program**. `docker run` args become its arguments. |
| `ENV` | Environment variable, persists into the running container. |
| `ARG` | Build-time only variable. **Not** a secret — visible in `docker history`. |
| `EXPOSE` | Documentation. Publishes nothing. |
| `USER` | Drop privileges. |
| `HEALTHCHECK` | Command Docker runs to decide healthy/unhealthy. |

### ENTRYPOINT vs CMD

The pairing we use:

```dockerfile
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The entrypoint always runs and receives the CMD as `"$@"`. So:

- `docker run api` → entrypoint runs, then uvicorn.
- `docker run api python -m app.seed` → entrypoint runs (DB wait, migrations),
  then the seed script. The setup logic cannot be accidentally skipped.

### Exec form vs shell form, and why PID 1 matters

```dockerfile
CMD ["uvicorn", "app.main:app"]     # exec form  — uvicorn IS pid 1
CMD uvicorn app.main:app            # shell form — /bin/sh is pid 1
```

`docker stop` sends SIGTERM to PID 1, waits 10s, then SIGKILL. A shell does not
forward signals to its children, so with the shell form your app never learns it
should shut down and every stop takes the full 10 seconds before being killed
mid-request. Always use the exec form, and `exec "$@"` at the end of an
entrypoint script — as `backend/docker-entrypoint.sh` does.

### Non-root

```dockerfile
RUN useradd --create-home --uid 10001 appuser
USER appuser
```

Container root is host uid 0. A kernel escape, a misconfigured mount, or a
privileged flag turns that into host root. The frontend goes further and uses
`nginxinc/nginx-unprivileged`, which never starts a root master process.

---

## 4. Running a single container

Before Compose, do it by hand once — it makes clear what Compose is automating.

```bash
docker build -t finance-api ./backend

docker run --rm \
  -e DATABASE_URL='postgresql+psycopg://finance:finance@host.docker.internal:5432/finance' \
  -e WAIT_FOR_DB=0 -e RUN_MIGRATIONS=0 \
  -p 8000:8000 \
  finance-api
```

| Flag | Meaning |
|---|---|
| `--rm` | Delete the container when it exits. Without it, stopped containers accumulate. |
| `-e` | Set an environment variable. |
| `-p 8000:8000` | Publish **host** port 8000 → **container** port 8000. Always `host:container`. |
| `-d` | Detach (run in background). |
| `-it` | Interactive + TTY, for shells. |
| `-v` | Mount a volume or host path. |
| `--name` | Give it a stable name instead of `nostalgic_curie`. |

Poke at it:

```bash
docker ps                          # running containers
docker ps -a                       # including stopped
docker logs -f finance-api         # follow stdout/stderr
docker exec -it finance-api sh     # shell inside a RUNNING container
docker inspect finance-api         # full JSON: mounts, env, network, health
docker stop finance-api
```

You will immediately notice the annoyances: the database is somewhere else,
`host.docker.internal` is a workaround, the env vars are a wall of `-e` flags,
and nothing restarts anything. That is the problem Compose solves.

---

## 5. Compose: the whole stack

`docker-compose.yml` declares four services — `db`, `cache`, `api`, `web` —
and Compose gives you, for free:

- one **project network** where service names are DNS names,
- **named volumes** created and attached,
- **dependency ordering** with health conditions,
- one command to build, start, stop and log everything.

```bash
cp .env.example .env      # do this first
docker compose up         # build if needed, start everything, stream logs
docker compose up -d      # same, detached
docker compose ps         # what is running and its health
docker compose logs -f api
docker compose down       # stop and remove containers + network (volumes SURVIVE)
docker compose down -v    # ...and delete volumes. This DELETES YOUR DATABASE.
```

Then open:

| URL | What |
|---|---|
| http://localhost:5173 | The dashboard |
| http://localhost:8000/api/docs | Interactive API docs (Swagger) |
| http://localhost:8000/health/ready | Readiness probe |

If a port is already taken you get `failed to bind host port ...: address
already in use`. Only the **host** side of a mapping can collide, so the fix is
to change that side and leave the container alone — set `WEB_PORT` / `API_PORT`
in `.env`:

```yaml
ports:
  - "127.0.0.1:${WEB_PORT:-5173}:5173"
```

Find the culprit with `ss -ltnp | grep 5173`.

The demo dataset loads automatically on first start (`SEED_DEMO_DATA=1`). To
reload it by hand:

```bash
docker compose exec api python -m app.seed
```

### `docker compose up` vs `start` vs `run`

| Command | Does |
|---|---|
| `up` | Create (and build if needed) + start. The one you want 95% of the time. |
| `start` | Start *existing* stopped containers. No rebuild, no recreate. |
| `run` | One-off container for a command: `docker compose run --rm api pytest`. |
| `exec` | Run a command in an **already running** container. |
| `build` | Build images without starting. `--no-cache` to force a clean build. |

A build change needs `docker compose up --build`. Compose does **not** rebuild
on Dockerfile edits by itself.

---

## 6. The development loop

The goal is that editing a file on your host changes behaviour immediately,
without a rebuild. Two mechanisms, one per service.

**Backend.** `docker-compose.yml` bind-mounts `./backend` over `/app` and
overrides the command to add `--reload`:

```yaml
volumes:
  - ./backend:/app
command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

The image still contains a copy of the source; the mount shadows it. Save a
`.py` file, uvicorn restarts.

**Frontend.** Same bind mount, plus one line that trips up everybody:

```yaml
volumes:
  - ./frontend:/app
  - /app/node_modules      # anonymous volume masking the bind mount
```

Without the second line, mounting `./frontend` over `/app` hides the
`node_modules` that was installed *inside* the image — and Vite fails to start.
The anonymous volume re-exposes the container's own `node_modules` at that
path. Remember this idiom; you will need it in every Node project.

**When you must rebuild:**

| Change | Command |
|---|---|
| Source file (mounted) | Nothing — hot reload handles it |
| `requirements.txt` / `package.json` | `docker compose up --build` |
| Dockerfile | `docker compose up --build` |
| `docker-compose.yml` | `docker compose up -d` (recreates changed services) |
| `.env` | `docker compose up -d` (env is read at container creation) |

**If file changes are not detected** (common on macOS/Windows, where inotify
events do not always cross the VM boundary), set `VITE_USE_POLLING=1` in
`.env`.

---

## 7. Data: volumes vs bind mounts

Three ways to get data into a container, and picking wrong is the usual cause
of "I lost my database".

| Kind | Syntax | Use for |
|---|---|---|
| **Named volume** | `pgdata:/var/lib/postgresql/data` | Persistent app state. Docker-managed, correct permissions, backup-able. |
| **Bind mount** | `./backend:/app` | Dev source code. Host path, host permissions. |
| **tmpfs** | `tmpfs: [/tmp]` | Scratch space in RAM. Never touches disk. |

Our database uses a named volume, deliberately:

```yaml
volumes:
  - pgdata:/var/lib/postgresql/data
```

A bind mount here would work on Linux and then break on macOS, and would give
Postgres a directory owned by the wrong uid. Named volumes avoid both.

```bash
docker volume ls
docker volume inspect finance_pgdata
docker compose down            # containers gone, pgdata SURVIVES
docker compose down -v         # pgdata DELETED
```

**Back up the database** (do this before any migration you are unsure about):

```bash
docker compose exec -T db pg_dump -U finance finance | gzip > backup-$(date +%F).sql.gz

# restore
gunzip -c backup-2026-08-17.sql.gz | docker compose exec -T db psql -U finance finance
```

`-T` disables TTY allocation, which is required when piping.

---

## 8. Networking

Compose creates a user-defined bridge network per project and attaches every
service. On it, **service names resolve as hostnames** via Docker's embedded
DNS at `127.0.0.11`. That is why our config says:

```
DATABASE_URL=postgresql+psycopg://finance:finance@db:5432/finance
REDIS_URL=redis://cache:6379/0
```

`db` and `cache` are service names, not hosts you configured anywhere.

Three rules that cover most networking confusion:

1. **Inside the network, use the service name and the container port.** The api
   reaches Postgres at `db:5432` whether or not port 5432 is published.
2. **`ports:` is only for reaching a container from the host.** It is not
   needed for container-to-container traffic. Every published port is exposure
   you may not want.
3. **Bind to `0.0.0.0` inside a container.** Binding `127.0.0.1` makes the
   process reachable only from that container's own loopback, so a published
   port connects to nothing. This is the #1 "why can't I reach my app".

### Publishing safely

Note the form we use:

```yaml
ports:
  - "127.0.0.1:5432:5432"      # host loopback only
```

not `"5432:5432"`. This matters more than it looks: **Docker publishes ports by
writing iptables rules in the `DOCKER` chain, which is evaluated before ufw's
rules.** A bare `"5432:5432"` on a VPS is reachable from the internet even
with `ufw` enabled and "deny incoming" set. In `docker-compose.prod.yml` the
database and api publish nothing at all; only Caddy binds 80/443.

### The nginx DNS trap

`frontend/nginx.conf` contains:

```nginx
resolver 127.0.0.11 valid=10s ipv6=off;
location /api/ {
    set $upstream http://api:8000;
    proxy_pass $upstream;
}
```

Without the resolver and the *variable*, nginx resolves `api` once at startup
and caches that IP forever. Restart the api container, it gets a new IP, and
nginx serves 502s until nginx itself is restarted. Using a variable in
`proxy_pass` forces runtime resolution. This bites nearly everyone once.

---

## 9. Configuration and secrets

The rule: **the image is identical across environments; only the environment
differs.** If dev and prod need different images, something is baked in that
should not be.

`backend/app/config.py` reads everything from the environment via
pydantic-settings. Compose supplies it, with defaults for dev:

```yaml
environment:
  MARKET_PROVIDER: ${MARKET_PROVIDER:-demo}     # default if unset
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}   # prod: fail loudly
```

`${VAR:-default}` falls back; `${VAR:?message}` aborts the command. Production
should never silently default a password.

### Where secrets must not go

- **Not in the image.** `ENV API_KEY=...` and `ARG API_KEY` are both readable
  via `docker history`. Layers are distributed with the image.
- **Not in git.** `.env` is gitignored; `.env.example` documents the shape.
- **Not in the build context.** `.dockerignore` excludes `.env` so `COPY . .`
  cannot capture it.

For a single VPS, a root-owned `.env` on the server (`chmod 600`) is the
honest answer. Beyond one box, use Docker secrets (Swarm), your cloud's secret
manager, or SOPS-encrypted files.

### HOME, uids, and libraries that write to `~`

A worked example from this repo, because it bites in a way that only shows up
in production.

OpenBB writes `~/.openbb_platform/` when imported and offers no environment
variable to relocate it — `openbb_core` reads `Path.home()` directly. That
collides with two things containers do:

1. **`user:` with a uid that has no `/etc/passwd` entry.** The dev compose file
   runs the api as `${DOCKER_UID:-1000}` so bind-mounted files stay yours, but
   the image only knows `appuser` (uid 10001). With no passwd entry Docker sets
   `HOME=/`, and the import dies with:

   ```
   Permission denied: '/.openbb_platform'
   ```

2. **`read_only: true`.** Even with a correct `HOME=/home/appuser`, a read-only
   root filesystem cannot be written:

   ```
   OSError: [Errno 30] Read-only file system: '/home/appuser/.openbb_platform'
   ```

The second one is the dangerous case: dev is fine, production fails at import.
Both are fixed by pointing `HOME` at a writable path — `/tmp`, which the prod
overlay already backs with a tmpfs:

```yaml
environment:
  HOME: /tmp
tmpfs:
  - /tmp
```

Verify a read-only image before deploying it, rather than finding out live:

```bash
docker run --rm --read-only --tmpfs /tmp -e HOME=/tmp \
  --entrypoint python finance-api -c "from openbb import obb; print('ok')"
```

The general lesson: **any dependency that writes to `$HOME`, `/app`, or its own
`site-packages` at runtime will break under `read_only`.** Do that work at
build time where you can, and give it a tmpfs where you can't.

### Generated code belongs in the image

OpenBB also generates ~38 Python modules into
`site-packages/openbb/package/` on first import. Left to runtime that costs
~30s on the first request, repeats in every replica, and is impossible under
`read_only`. The Dockerfile does it once, at build time:

```dockerfile
RUN python -c "import openbb" || true
```

Confirm it actually got baked in:

```bash
docker run --rm --entrypoint sh finance-api \
  -c 'ls /opt/venv/lib/python3.12/site-packages/openbb/package/ | wc -l'
```

### One trap worth naming

For a Vite frontend, `VITE_*` variables are substituted **at build time** and
end up in the JS bundle. They are not runtime config and are not secret — they
ship to every browser. That is exactly why this app calls relative `/api` URLs
and lets nginx proxy, instead of baking an API URL into the bundle: one image
works behind any hostname.

---

## 10. Healthchecks and startup order

`depends_on` alone only orders *starts*. Postgres accepts connections several
seconds after its container starts, so plain `depends_on` gives you a
crash-looping api on every fresh boot.

The fix is a healthcheck plus a condition:

```yaml
db:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U finance -d finance"]
    interval: 5s
    retries: 10
    start_period: 10s

api:
  depends_on:
    db:
      condition: service_healthy
```

`start_period` is the grace window: failures during it do not count toward
`retries`, so a slow-starting service is not killed for being slow.

The api exposes two probes (`backend/app/routers/health.py`), and the
distinction is worth internalising:

- **`/health/live`** — "is the process wedged?" Touches nothing. If this
  checked the database, a 5-second DB blip would get your healthy app killed.
- **`/health/ready`** — "should traffic reach me?" Checks Postgres (required)
  and Redis (optional — a dead cache is *degraded*, not unready).

Even with all that, `docker-entrypoint.sh` retries the DB connection itself.
Compose conditions do not exist under plain `docker run`, and a container must
tolerate its dependencies restarting under it.

```bash
docker compose ps                     # STATUS column shows (healthy)/(unhealthy)
docker inspect --format '{{json .State.Health}}' finance-api-1 | python3 -m json.tool
```

---

## 11. Migrations

Schema changes ship as versioned files (`backend/alembic/versions/`), applied
by the entrypoint before the app starts:

```sh
alembic upgrade head
```

Because `set -e` is on, a failed migration stops the container rather than
starting an app against a half-migrated schema.

```bash
# after editing models.py, generate a migration against the running DB
docker compose exec api alembic revision --autogenerate -m "add dividend column"
docker compose exec api alembic upgrade head
docker compose exec api alembic downgrade -1
docker compose exec api alembic current
```

Autogenerate writes into the bind-mounted `./backend`, so the new file appears
on your host, ready to commit. **Always read what it generated** — it detects
added/removed columns well, and renames not at all (it emits a drop plus an
add, which loses data).

For that write to succeed, the dev `api` service runs as your host uid:

```yaml
user: "${DOCKER_UID:-1000}:${DOCKER_GID:-1000}"
```

A bind mount passes host ownership straight into the container — it does not
remap uids. Without this, the container's `appuser` (uid 10001) cannot write
into a directory owned by uid 1000, and any file it *did* create would appear
on your host owned by a user that does not exist there. Set `DOCKER_UID`/
`DOCKER_GID` in `.env` to your own (`id -u`, `id -g`) if you are not 1000.
Production drops it (`user: !reset null`) and uses the image's non-root user,
because production has no bind mount.

**The scaling caveat**, stated in the entrypoint comments: with N replicas, N
containers race to migrate on startup. Alembic takes a lock so it is usually
survivable, but the correct pattern past one node is a separate one-shot job —
a Compose profile, or a Kubernetes initContainer — with the app containers
starting only after it succeeds.

---

## 12. Building for production

`docker-compose.prod.yml` is an **overlay**, not a replacement:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Compose merges left to right. The rule that catches people: **scalars are
replaced, lists are appended.** Left alone, the dev bind mount `./backend:/app`
would survive into production and shadow your built image with host source.
Hence every list is explicitly cleared first:

```yaml
api:
  volumes: !reset []     # drop the dev bind mount
  command: !reset null   # fall back to the image CMD (no --reload)
  ports: !reset []       # only nginx talks to the api
```

Verify the merge before trusting it:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

That prints the fully resolved configuration with variables substituted. Read
it once for every production change.

What else the overlay changes:

| Setting | Why |
|---|---|
| `target: runtime` for web | nginx serving `dist/`, not the Vite dev server |
| `read_only: true` + `tmpfs` | The app writes nothing outside /tmp; make that a guarantee |
| `security_opt: no-new-privileges` | Blocks setuid privilege escalation |
| `deploy.resources.limits.memory` | Without it, one container can OOM the host and the kernel may kill Postgres |
| `logging.options.max-size` | Unbounded json-file logs are the #1 way a small VPS fills its disk |
| `proxy` (Caddy) | TLS termination with automatic Let's Encrypt certificates |

---

## 13. Registries

Building on the server is a bad default: builds need a toolchain, RAM and cache
that a small VPS should not spend, and a failed build leaves you with a broken
deploy. Build somewhere else, push an image, pull it on the server.

```bash
# authenticate (GitHub Container Registry; a PAT with write:packages)
echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_USERNAME --password-stdin

# set REGISTRY and TAG in .env, then
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml push
```

An image reference is `registry/namespace/name:tag` —
`ghcr.io/yourname/finance-api:0.2.0`.

**Do not deploy `:latest`.** It is a mutable pointer: `docker pull` may or may
not get what you tested, and you cannot roll back to "the previous latest". Tag
with something immutable — a version or the git SHA:

```bash
TAG=$(git rev-parse --short HEAD) docker compose -f docker-compose.yml -f docker-compose.prod.yml build
```

Rolling back then means setting `TAG` to the previous SHA and running `up -d`.

**Multi-arch**: if you build on an Apple Silicon Mac and deploy to an x86 VPS,
the image will not run. Build for the target platform explicitly:

```bash
docker buildx build --platform linux/amd64,linux/arm64 --push \
  -t ghcr.io/yourname/finance-api:$TAG ./backend
```

---

## 14. Deploying to a VPS

### One-time server setup

```bash
# on the server, as a sudo user
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # then log out and back in

sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Remember §8: ufw does not filter Docker-published ports. The real protection is
that `docker-compose.prod.yml` publishes nothing except Caddy's 80/443.

### Deploy

Only three files need to exist on the server:

```
~/finance/
├── docker-compose.yml
├── docker-compose.prod.yml
├── deploy/Caddyfile
└── .env                    # chmod 600, never in git
```

```bash
scp docker-compose.yml docker-compose.prod.yml server:~/finance/
scp -r deploy server:~/finance/
ssh server 'chmod 600 ~/finance/.env'
```

Point your domain's A record at the server, set `DOMAIN` in `.env`, then:

```bash
cd ~/finance
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Caddy requests a certificate on first start; it needs DNS already pointing at
the box and ports 80/443 reachable. Watch it work:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f proxy
```

### Updating

```bash
export TAG=$(git rev-parse --short HEAD)   # the tag you built and pushed
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker image prune -f
```

`up -d` recreates only containers whose configuration or image changed. There
is a brief gap while the api restarts — acceptable for a single-node
deployment. Zero-downtime needs two replicas behind the proxy and a rolling
restart, which is where you start reaching for Swarm or Kubernetes.

Save yourself the typing:

```bash
alias dcp='docker compose -f docker-compose.yml -f docker-compose.prod.yml'
```

---

## 15. Operating it

```bash
# logs
docker compose logs -f --tail=100 api
docker compose logs --since 30m

# resources — check this before blaming the app
docker stats

# disk: build cache and dangling images grow without bound
docker system df
docker system prune -a --volumes    # AGGRESSIVE: reads the warning first

# a psql shell
docker compose exec db psql -U finance finance

# restart one service
docker compose restart api
```

**Automate the backup.** A backup you run by hand is a backup you do not have:

```cron
0 3 * * * cd /home/you/finance && docker compose exec -T db pg_dump -U finance finance | gzip > /backups/finance-$(date +\%F).sql.gz
```

And restore from it at least once, on purpose, before you need to.

---

## 16. Debugging cheatsheet

| Symptom | Likely cause | Check |
|---|---|---|
| Container exits immediately | Main process finished or crashed | `docker compose logs <svc>` |
| `Connection refused` to your app | Bound to `127.0.0.1` inside the container | Must be `--host 0.0.0.0` |
| `could not translate host name "db"` | Not on the same network, or typo'd service name | `docker compose ps`, `docker network inspect finance_default` |
| API 502s after restarting a service | nginx cached the old container IP | The `resolver` + variable `proxy_pass` in nginx.conf |
| Code edits do nothing | No bind mount, or no `--reload`, or you rebuilt without it | `docker compose config` and check `volumes:` |
| Vite: "cannot find module" after mounting | Bind mount hid `node_modules` | Add the `- /app/node_modules` anonymous volume |
| `permission denied` on a mounted file | Container uid ≠ host file owner | `docker compose exec api id`, then `ls -ln` the file |
| DB "already exists"/schema mismatch | Old named volume from a previous schema | `docker compose down -v` (destroys data) |
| Build ignores your change | Cached layer | `docker compose build --no-cache <svc>` |
| Disk full | Build cache, dangling images, old volumes | `docker system df`, then prune |
| Works locally, not on the server | Architecture mismatch (arm64 vs amd64) | `docker image inspect --format '{{.Architecture}}'` |

Two commands that answer most questions:

```bash
docker compose config          # the fully-merged, variable-substituted config
docker inspect <container>     # mounts, env, network, health, exit code
```

To debug an image that will not start, bypass its entrypoint entirely:

```bash
docker run --rm -it --entrypoint sh finance-api
```

---

## 17. Common mistakes

1. **`COPY . .` before installing dependencies.** Destroys the build cache;
   every source edit reinstalls everything.
2. **No `.dockerignore`.** Slow builds, and secrets baked into layers.
3. **Running as root.** Free hardening, skipped by default.
4. **`:latest` in production.** Unreproducible deploys, no rollback.
5. **Secrets in `ENV`/`ARG`.** Readable in `docker history` by anyone with the
   image.
6. **Bind mount for a database.** Permission problems, no portability, easy to
   delete.
7. **`depends_on` without `condition: service_healthy`.** Start ordering is not
   readiness.
8. **Shell-form `CMD`.** No signal forwarding, 10-second stops, no graceful
   shutdown.
9. **Publishing a database port on a public interface.** And believing ufw is
   protecting it.
10. **Unbounded logging.** Fills the disk on a small server, weeks later.
11. **Log files inside the container.** Write to stdout; the runtime collects it.
12. **Forgetting lists append when merging Compose files.** Dev bind mounts
    silently reaching production.

---

## Where to go next

- **Tests in CI**: `docker compose run --rm api pytest`, then build and push on
  green.
- **Zero-downtime deploys**: two api replicas plus a rolling restart, or Swarm.
- **Image scanning**: `docker scout cves finance-api:latest`.
- **Smaller images**: distroless bases; `docker history` to find the fat layer.
- **Kubernetes**: worth it when you need multi-node scheduling and self-healing
  — and not before. Compose on one box carries a real application a long way.
