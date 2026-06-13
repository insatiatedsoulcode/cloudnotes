"""
Rate limiting (F-02) + Redis-backed storage (F-03c).

Storage tiers:
  memory://          — in-memory, single process only (tests, no Redis)
  redis://host:port  — Redis-backed, survives restarts, works across instances

Why Redis matters for rate limiting:
  With in-memory storage, each app instance has its own counters.
  If you run 3 ECS tasks, a user can make 5 × 3 = 15 login attempts before
  hitting the limit. Redis gives every instance a shared, consistent counter.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings


def _get_user_or_ip(request: Request) -> str:
    """
    Key function for write endpoints: per JWT user when authenticated,
    per IP when not. Prevents one user on a shared IP from exhausting
    another user's quota (critical for university / office networks).
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            token = auth.split(" ", 1)[1]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except JWTError:
            pass
    return get_remote_address(request)


# storage_uri=settings.REDIS_URL → Redis in dev/prod ("redis://localhost:6379")
# In tests, conftest sets REDIS_URL="memory://" so no real Redis is needed.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    storage_uri=settings.REDIS_URL,
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return clean JSON 429 instead of slowapi's default plain-text response."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}. Try again later."},
        headers={"Retry-After": "60"},
    )


def reset_limits() -> None:
    """Clear all rate limit counters. Used in tests only."""
    limiter._limiter.storage.reset()
