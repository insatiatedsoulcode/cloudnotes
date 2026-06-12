# ── Stage 1: builder ──────────────────────────────────────────────────────────
# CLOUD ENGINEERING NOTE:
# Multi-stage builds keep the final image small. The builder stage installs
# all dependencies; only the installed packages make it into the final image —
# not pip, build tools, or cache files.
FROM python:3.12-slim AS builder

WORKDIR /app

# Install deps into a local directory so we can copy just that across stages
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

# CLOUD ENGINEERING NOTE:
# Never run containers as root. Create a dedicated user.
# If an attacker escapes the app, they're nobody on the host, not root.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/

# Switch to non-root
USER appuser

EXPOSE 8000

# CLOUD ENGINEERING NOTE:
# ECS / ALB will hit /health to decide if this container is healthy.
# If the check fails 3× in a row, ECS replaces the task.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
