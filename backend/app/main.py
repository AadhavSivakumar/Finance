import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import health, market

settings = get_settings()

# Log to stdout and let the container runtime handle collection. Never write
# log files inside a container: the filesystem dies with the container, and
# `docker logs` / journald / your log shipper all read stdout.
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(market.router)


@app.get("/api")
def root() -> dict:
    return {
        "name": settings.app_name,
        "environment": settings.environment,
        "market_provider": settings.market_provider,
        "docs": "/api/docs",
    }
