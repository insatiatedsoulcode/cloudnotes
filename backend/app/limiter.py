from fastapi import Request
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings


def _get_user_or_ip(request: Request) -> str:
    """
    Key function for write endpoints: identify by user ID when authenticated,
    fall back to IP for unauthenticated requests.

    This makes limits per-user rather than per-IP, so shared IPs (office NAT,
    university networks) don't have one user exhaust another's quota.
    Redis-backed distributed limits come in F-03.
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


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
    # headers_enabled requires `response: Response` in every route signature.
    # We skip it here and rely on the custom 429 handler for Retry-After instead.
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return JSON 429 instead of slowapi's default plain-text response."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}. Try again later."},
        headers={"Retry-After": "60"},
    )


def reset_limits() -> None:
    """Clear all in-memory rate limit counters. Used in tests only."""
    limiter._limiter.storage.reset()
