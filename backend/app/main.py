import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.logger import get_logger, setup_logging
from app.routers import auth, notes

setup_logging()
log = get_logger("app")

# Run any pending Alembic migrations on startup.
# In production this would be a separate pre-deploy step; here it keeps
# local dev simple — just start the server and the schema is always current.
_alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
command.upgrade(_alembic_cfg, "head")
log.info("Database migrations applied")

app = FastAPI(
    title="CloudNotes API",
    description="A simple notes app — POC for cloud engineering concepts",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(notes.router, prefix="/api")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_log = get_logger("request")
    res_log = get_logger("response")

    body_preview = ""
    if request.method not in ("GET", "DELETE"):
        raw = await request.body()
        body_preview = raw.decode()[:300]

    req_log.info("%s %s  body=%s", request.method, request.url.path, body_preview or "<empty>")

    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - t0) * 1000

    res_log.info(
        "%s %s  status=%d  duration=%.1fms",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "CloudNotes API", "docs": "/docs"}
