import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.admin.addresses import router as admin_addresses_router
from app.api.v1.admin.audit import router as admin_audit_router
from app.api.v1.admin.bulk import router as admin_bulk_router
from app.api.v1.admin.hierarchy import router as admin_hierarchy_router
from app.api.v1.admin.map import router as admin_map_router
from app.api.v1.admin.stats import router as admin_stats_router
from app.api.v1.admin.technologies import router as admin_technologies_router
from app.api.v1.admin.users import router as admin_users_router
from app.api.v1.admin.zones import router as admin_zones_router
from app.api.v1.public.addresses import router as public_addresses_router
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.errors import (
    http_exception_handler,
    raise_error,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.limiter import limiter
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware
from app.telemetry import configure_telemetry

log = logging.getLogger(__name__)

configure_logging()

_TAGS = [
    {"name": "admin-addresses", "description": "Address search, details and address-level offerings"},
    {"name": "admin-zones", "description": "Service zones (polygons) and zone offerings"},
    {"name": "admin-users", "description": "User accounts and API keys"},
    {"name": "admin-technologies", "description": "Technology type catalog"},
    {"name": "admin-audit", "description": "Audit log queries"},
    {"name": "admin-bulk", "description": "Bulk operations: preview / execute / rollback"},
    {"name": "admin-hierarchy", "description": "Cascading dropdowns: county → municipality → locality → street"},
    {"name": "admin-map", "description": "GeoJSON map tiles and polygon search"},
    {"name": "admin-stats", "description": "Coverage statistics"},
    {"name": "public", "description": "Public unauthenticated endpoints"},
    {"name": "health", "description": "Liveness and readiness probes"},
]

app = FastAPI(
    title="Etanetas Address API",
    version="0.1.0",
    openapi_tags=_TAGS,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Include OPTIONS so browser preflight requests are handled by CORS middleware.
    allow_methods=["*"],
    allow_headers=["*"],
)
configure_telemetry(app, engine)

app.include_router(public_addresses_router)
app.include_router(admin_users_router)
app.include_router(admin_addresses_router)
app.include_router(admin_technologies_router)
app.include_router(admin_zones_router)
app.include_router(admin_audit_router)
app.include_router(admin_bulk_router)
app.include_router(admin_map_router)
app.include_router(admin_hierarchy_router)
app.include_router(admin_stats_router)


async def _db_ping() -> None:
    """Tiny DB round-trip; isolated so tests can monkeypatch."""
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))


@app.get("/health", tags=["health"], summary="Liveness + DB readiness probe", operation_id="health.check")
async def health() -> dict:
    try:
        await _db_ping()
    except SQLAlchemyError as exc:
        log.warning("DB health check failed: %s", exc)
        raise_error(503, "SERVICE_UNAVAILABLE", "Database unavailable")
    except TimeoutError:
        log.warning("DB health check timed out")
        raise_error(503, "SERVICE_UNAVAILABLE", "Database health check timed out")
    return {"status": "ok", "db": "up"}
