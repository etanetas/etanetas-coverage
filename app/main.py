from fastapi import FastAPI
from sqlalchemy import text

from app.database import AsyncSessionLocal, engine
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware
from app.telemetry import configure_telemetry

configure_logging()

app = FastAPI(
    title="Etanetas Address API",
    version="0.1.0",
)

app.add_middleware(RequestIDMiddleware)
configure_telemetry(app, engine)


@app.get("/health")
async def health():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": str(e)}, 503
