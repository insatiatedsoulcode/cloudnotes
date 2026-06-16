import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.limiter import limiter, rate_limit_exceeded_handler
from app.logger import get_logger, request_id_var, setup_logging
from app.routers import admin, attachments, auth, notes, sharing, tags, users

setup_logging()
log = get_logger("app")

# Run any pending Alembic migrations on startup.
# In production this would be a separate pre-deploy step; here it keeps
# local dev simple — just start the server and the schema is always current.
_alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
command.upgrade(_alembic_cfg, "head")
log.info("Database migrations applied")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV != "test":
        from app.scheduler import start_scheduler, stop_scheduler
        start_scheduler()
        yield
        stop_scheduler()
    else:
        yield


app = FastAPI(
    title="CloudNotes API",
    description="A simple notes app — POC for cloud engineering concepts",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiter — must be set on app.state before SlowAPIMiddleware is added
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Version", "X-Request-ID"],
)

# ── F-16: API versioning ───────────────────────────────────────────────────────
# Primary versioned routes (/api/v1/) appear in OpenAPI docs.
# Legacy /api/ aliases are kept for backwards compatibility but hidden from docs.
# Header versioning: clients may also send Accept-Version: v1 on /api/ routes.
_ROUTERS = [auth.router, notes.router, sharing.router, attachments.router,
            admin.router, tags.router, users.router]

for _r in _ROUTERS:
    app.include_router(_r, prefix="/api/v1")               # primary (in docs)
    app.include_router(_r, prefix="/api", include_in_schema=False)  # legacy alias

# Serve uploaded files as static assets.
# In production, swap for a CDN/S3 URL — no app-server traffic for binary files.
_uploads_dir = Path(settings.UPLOADS_DIR)
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

_SUPPORTED_VERSIONS = {"v1"}


@app.middleware("http")
async def api_middleware(request: Request, call_next):
    req_log = get_logger("request")
    res_log = get_logger("response")

    # F-16: Validate Accept-Version header when present.
    version = request.headers.get("Accept-Version")
    if version is not None and version not in _SUPPORTED_VERSIONS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Unsupported API version: {version!r}. Supported versions: v1"},
        )

    # F-15: Per-request correlation ID.
    rid = str(uuid.uuid4())
    request_id_var.set(rid)

    # F-17: Content-Type enforcement on mutation endpoints with a JSON body.
    if request.method in ("POST", "PUT", "PATCH"):
        ct = request.headers.get("content-type", "")
        allowed = ("application/json", "application/x-www-form-urlencoded", "multipart/form-data")
        if ct and not any(ct.startswith(a) for a in allowed):
            return JSONResponse(
                status_code=415,
                content={"detail": "Unsupported Media Type. Use application/json."},
            )

    body_preview = ""
    if request.method not in ("GET", "DELETE"):
        ct = request.headers.get("content-type", "")
        if "multipart/" in ct:
            body_preview = "<binary upload>"
        else:
            raw = await request.body()
            body_preview = raw.decode(errors="replace")[:300]

    req_log.info("%s %s  body=%s", request.method, request.url.path, body_preview or "<empty>")

    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - t0) * 1000

    response.headers["X-Request-ID"] = rid

    res_log.info(
        "%s %s  status=%d  duration_ms=%.1f",
        request.method, request.url.path, response.status_code, duration_ms,
        extra={"duration_ms": round(duration_ms, 1), "status_code": response.status_code},
    )
    return response


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "CloudNotes API", "docs": "/docs"}
