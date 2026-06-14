"""
Central logging setup for CloudNotes (F-15).

Two output modes controlled by LOG_FORMAT env var:
  "text" (default) — human-readable, good for local dev
  "json"           — structured JSON, ingested by CloudWatch Logs / Datadog / Loki

Log level per environment:
  production  → INFO  (no debug noise in prod)
  test        → WARNING (suppressed by pytest's log capture)
  everything  → DEBUG

Request ID (correlation ID):
  A UUID is generated per HTTP request by the middleware and stored in
  `request_id_var` (a contextvars.ContextVar).  The RequestContextFilter
  injects it into every log record emitted during that request so that
  all lines for one request share the same ID — essential for tracing
  across a microservice graph.

Cloud analogy:
  - JSON → CloudWatch Logs Insights can query `fields @message | filter request_id = "..."`.
  - Correlation IDs are the simplest form of distributed tracing (X-Ray / Jaeger step up from here).
  - Log level is an operational dial: flip DEBUG→INFO with a single env var, no redeploy.

Dataflow through the layers (read top-to-bottom when watching logs):
  Browser fetch()
    → Vite dev proxy  (/api → :8000)
      → FastAPI middleware   [cloudnotes.request] + [cloudnotes.response]
        → Router function    [cloudnotes.notes]
          → get_db()         [cloudnotes.db]
            → SQLAlchemy     [sqlalchemy.engine]
          ← session close    [cloudnotes.db]
        ← router returns     [cloudnotes.notes]
      ← middleware records   [cloudnotes.response]
    ← HTTP response
  Browser receives JSON
"""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter as _JsonFormatter

# ── Per-request correlation ID ────────────────────────────────────────────────

# Set by the request middleware at the start of every HTTP request.
# Any coroutine spawned within that request task inherits this value.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class _RequestContextFilter(logging.Filter):
    """Inject the current request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("")
        return True


# ── Formatters ────────────────────────────────────────────────────────────────

_TEXT_FMT = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s  rid=%(request_id)s"
_TEXT_DATE = "%H:%M:%S"

_JSON_FMT = "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s"


# ── Level per environment ─────────────────────────────────────────────────────

def _level_for_env(app_env: str) -> int:
    env = app_env.lower()
    if env == "production":
        return logging.INFO
    if env == "test":
        return logging.WARNING
    return logging.DEBUG


# ── Public API ────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    from app.config import settings

    level = _level_for_env(settings.APP_ENV)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestContextFilter())

    if settings.LOG_FORMAT == "json":
        formatter = _JsonFormatter(
            fmt=_JSON_FMT,
            datefmt="%Y-%m-%dT%H:%M:%SZ",
            rename_fields={"levelname": "level", "name": "logger", "asctime": "timestamp"},
        )
    else:
        formatter = logging.Formatter(_TEXT_FMT, datefmt=_TEXT_DATE)

    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # SQLAlchemy logs every SQL statement at INFO; DEBUG also shows result rows.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

    # Uvicorn's built-in access log is redundant — our middleware handles it.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cloudnotes.{name}")
