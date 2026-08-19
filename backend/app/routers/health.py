"""Liveness and readiness probes.

The distinction matters once this runs under an orchestrator:

* **live**  -- "is the process wedged?" Must not touch dependencies, or a brief
               database blip gets your app killed and restarted for no reason.
* **ready** -- "should traffic be routed here?" Checks dependencies, so a
               starting container is kept out of the load balancer until its
               database connection actually works.

Compose's ``healthcheck:`` and ``depends_on: condition: service_healthy`` use
the readiness endpoint.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..services import prices

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok", "environment": settings.environment}


@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)) -> dict:
    checks: dict[str, str] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        checks["database"] = f"error: {exc.__class__.__name__}"

    cache = prices.get_cache()
    if cache is None:
        # Cache is optional: absent means degraded, not unready.
        checks["cache"] = "unavailable"
    else:
        try:
            cache.ping()
            checks["cache"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["cache"] = f"error: {exc.__class__.__name__}"

    healthy = checks["database"] == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ok" if healthy else "unready", "checks": checks}
