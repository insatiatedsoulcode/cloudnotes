# ── Stage 1: builder ──────────────────────────────────────────────────────────
# CLOUD ENGINEERING NOTE:
# Multi-stage builds keep the final image small. The builder stage installs
# all dependencies; only the installed packages make it into the final image —
# not pip, build tools, or cache files.
FROM python:3.11-slim AS builder

WORKDIR /app

# Install deps into an isolated prefix so we can copy just that across stages.
# --no-cache-dir keeps the layer small (no pip download cache written to disk).
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

# CLOUD ENGINEERING NOTE:
# Never run containers as root. A dedicated system user limits blast radius
# if an attacker escapes the app — they're nobody on the host, not root.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Alembic migrations are run at startup (via main.py → alembic.upgrade head).
# Both the config file and the versioned migration scripts must be present.
COPY alembic.ini .
COPY alembic/ ./alembic/

# Create uploads directory with correct ownership before switching to non-root.
# When Docker mounts the named volume here, it inherits these permissions.
# CLOUD EQUIVALENT: EFS access point with posix user config, or just use S3.
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app/uploads

USER appuser

EXPOSE 8000

# CLOUD ENGINEERING NOTE:
# ECS / ALB hits /health to decide if this container is healthy.
# 3 consecutive failures → ECS replaces the task automatically.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
