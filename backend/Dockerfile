# syntax=docker/dockerfile:1.7
# ^ Opts into the modern BuildKit frontend, which is what makes `--mount=type=cache`
#   below legal. Without this line you get the 1.0 parser and a syntax error.

# ---------------------------------------------------------------------------
# Stage 1: base
#
# Every stage starts FROM some image. `python:3.12-slim` is Debian trixie with
# CPython preinstalled. Three flavours exist and the choice is a real tradeoff:
#   python:3.12          ~1GB  full Debian, has compilers, gcc, git
#   python:3.12-slim     ~150MB no build toolchain, glibc  <-- our pick
#   python:3.12-alpine   ~60MB  musl libc; smaller, but many wheels have no musl
#                              build so pip compiles from source -> slower builds
#                              and occasional subtle C-extension bugs
#
# Pin the minor version (3.12), not `latest`: a base image that silently moves
# to 3.13 in six months is a reproducibility bug waiting to happen.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

# ENV values persist into the running container; ARG values do not.
ENV PYTHONUNBUFFERED=1 \
    # ^ stdout is block-buffered when not a TTY, so without this your logs
    #   appear minutes late (or never, if the container is killed).
    PYTHONDONTWRITEBYTECODE=1 \
    # ^ .pyc files in a container are write amplification: they bloat the layer
    #   and are regenerated anyway.
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------------------------------------------------------------------------
# Stage 2: builder -- compile/collect dependencies into a virtualenv
#
# Why a separate stage: build-time needs (gcc, headers, pip's own machinery)
# are not runtime needs. Anything installed here that we do not COPY forward
# never reaches the final image, so it costs nothing in size or attack surface.
# ---------------------------------------------------------------------------
FROM base AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
    # ^ All three commands in ONE RUN. If `rm` were a separate RUN, the apt
    #   lists would already be baked into the previous layer and deleting them
    #   later would ADD a layer rather than shrink the image. Layers are
    #   append-only; you cannot delete your way to a smaller image.

# A venv, copied wholesale into the runtime stage. Cleaner than --user installs
# and keeps our packages away from the distro's Python.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# THE most important caching decision in this file: copy the dependency
# manifest ALONE, install, and only then copy source. Docker caches each
# instruction keyed on the files it touches, so editing app/main.py does not
# invalidate the pip install layer. Copy the whole tree first and every source
# edit re-downloads every package.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
    # ^ BuildKit cache mount: pip's HTTP cache survives *between* builds without
    #   being stored in any layer. Even a cache-busted rebuild reuses downloads.

# Pre-build OpenBB's static interface AT BUILD TIME.
#
# On its first import OpenBB generates ~39 Python modules and writes them into
# site-packages/openbb/package/. Skipping this step means the first HTTP
# request pays ~30s, every replica repeats the work, and -- fatally -- it
# breaks outright under the production overlay's `read_only: true`, because
# site-packages is then not writable. Doing it here bakes the generated code
# into the image, where it belongs.
#
# `|| true` because the build is an optimisation: a transient failure here
# must not fail the whole image build.
RUN python -c "import openbb" || true

# ---------------------------------------------------------------------------
# Stage 3: runtime -- what actually ships
# ---------------------------------------------------------------------------
FROM base AS runtime

# libpq5 is the runtime half of libpq-dev; psycopg needs it, but we do not need
# the headers or gcc that built it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user. Containers are not a security boundary by themselves:
# root inside the container is uid 0 on the host kernel, so a container escape
# or a bad bind mount becomes host root. This is the single cheapest hardening
# step available.
RUN useradd --create-home --uid 10001 appuser

# Model-artefact directory, created in the IMAGE so the named volume mounted
# here inherits these permissions. Docker initialises an empty named volume
# from the image path; when the path does not exist it creates it root-owned,
# and a container running as any other uid then cannot write -- which is
# exactly the "Permission denied: /models/..." failure this avoids.
#
# Mode 1777 (sticky, like /tmp) because the dev container runs as the host
# user's uid, which is not knowable at build time. In production the container
# runs as appuser and the sticky bit still prevents cross-user deletion.
RUN mkdir -p /models && chmod 1777 /models

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# --chown avoids a second layer that would duplicate every file just to change
# its ownership bits.
COPY --chown=appuser:appuser . .

USER appuser

# Documentation only -- EXPOSE publishes nothing. Actual publishing is
# `docker run -p` or Compose's `ports:`.
EXPOSE 8000

# Compose overrides this with a readier check, but a HEALTHCHECK in the image
# means `docker run` alone still reports health.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# ENTRYPOINT is the fixed program; CMD is the default argument list. Splitting
# them this way means `docker compose run api bash` still goes through the
# entrypoint's migration/wait logic, and the exec-form (JSON array) means no
# shell wraps the process -- so uvicorn is PID 1 and receives SIGTERM directly
# for a graceful shutdown.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
#                                        ^^^^^^^ binding to 127.0.0.1 inside a
# container makes it reachable only from that container's own loopback -- the
# single most common "why can't I reach my app" mistake.

# ---------------------------------------------------------------------------
# Stage 4: dev -- runtime plus test tooling.
#
# Layered ON TOP of runtime so the thing you test is the thing you ship, with
# only test dependencies added. docker-compose.yml targets this stage;
# docker-compose.prod.yml targets `runtime`, so pytest and friends never reach
# production -- they are dead weight and extra CVE surface there.
#
# This also exists because you cannot `pip install` into a running container:
# /opt/venv is owned by appuser and the dev container runs as your host uid.
# Install-at-build-time is the containerised answer to that, not chmod.
# ---------------------------------------------------------------------------
FROM runtime AS dev

USER root
COPY requirements-dev.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-dev.txt
USER appuser
