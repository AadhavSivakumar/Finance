#!/usr/bin/env sh
# Container entrypoint: get the environment into a known-good state, then hand
# over to the real process.
#
# `set -e` aborts on the first failure, so a failed migration stops the
# container instead of starting an app against a half-migrated schema.
set -e

log() { echo "[entrypoint] $*"; }

# ---------------------------------------------------------------------------
# 1. Wait for Postgres.
#
# Compose's `depends_on: service_healthy` already handles ordering, but this
# script also runs under `docker run`, Kubernetes, and a VPS restart where the
# DB may lag. Retrying here is cheap insurance -- containers must tolerate
# their dependencies being temporarily absent.
# ---------------------------------------------------------------------------
if [ "${WAIT_FOR_DB:-1}" = "1" ]; then
  log "waiting for database..."
  python - <<'PY'
import os
import sys
import time

import psycopg

url = os.environ.get("DATABASE_URL", "")
# SQLAlchemy's driver suffix is not valid libpq syntax.
dsn = url.replace("postgresql+psycopg://", "postgresql://")

deadline = time.monotonic() + float(os.environ.get("DB_WAIT_TIMEOUT", "60"))
last = None
while time.monotonic() < deadline:
    try:
        with psycopg.connect(dsn, connect_timeout=3):
            print("[entrypoint] database is up")
            sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last = exc
        time.sleep(1)

print(f"[entrypoint] database unreachable: {last}", file=sys.stderr)
sys.exit(1)
PY
fi

# ---------------------------------------------------------------------------
# 2. Migrate.
#
# Running migrations in the entrypoint is the pragmatic single-node choice. Be
# aware of the tradeoff: with N replicas, N containers race to migrate at once.
# Alembic takes a lock so this is usually survivable, but at scale you move
# migrations to a separate one-shot job (Compose profile / K8s initContainer).
# ---------------------------------------------------------------------------
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  log "running migrations"
  alembic upgrade head
fi

if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
  log "seeding demo data"
  python -m app.seed
fi

log "starting: $*"

# `exec` REPLACES this shell with the target process, so the app becomes PID 1
# and receives SIGTERM from `docker stop` directly. Without exec, the shell
# stays PID 1, does not forward signals, and every shutdown takes the full
# 10-second timeout before a SIGKILL.
exec "$@"
