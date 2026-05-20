from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from viewer.routes import router

app = FastAPI(title="Etanetas Viewer", version="0.1.0")

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
app.include_router(router)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "map.html")


@app.get("/lms")
async def lms() -> FileResponse:
    return FileResponse(_STATIC / "lms.html")
