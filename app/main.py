from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api.v1.admin.addresses import router as admin_addresses_router
from app.api.v1.admin.audit import router as admin_audit_router
from app.api.v1.admin.bulk import router as admin_bulk_router
from app.api.v1.admin.technologies import router as admin_technologies_router
from app.api.v1.admin.users import router as admin_users_router
from app.api.v1.admin.zones import router as admin_zones_router
from app.api.v1.public.addresses import router as public_addresses_router
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.limiter import limiter
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware
from app.telemetry import configure_telemetry

configure_logging()

app = FastAPI(
    title="Etanetas Address API",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
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


@app.get("/health")
async def health():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": str(e)}, 503
