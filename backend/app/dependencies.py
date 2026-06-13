"""
Auth dependencies — injected into route functions via FastAPI's Depends().

How JWT auth works in this app:
  1. Client logs in → server returns a signed JWT token
  2. Client stores token and sends it as:  Authorization: Bearer <token>
  3. get_current_user() decodes the token, looks up the user in DB, returns it
  4. Routes that need auth declare:  current_user: User = Depends(get_current_user)
  5. Routes that need admin declare:  current_user: User = Depends(require_admin)

The token is STATELESS — the server never stores it. It's valid until it expires
(JWT_EXPIRE_MINUTES). This is what makes horizontal scaling work: any instance
can verify any token without sharing session state.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.logger import get_logger
from app.models.user import User

log = get_logger("auth")

# Tells FastAPI where the login endpoint is (used for Swagger UI auth button)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        sub = payload.get("sub")
        if sub is None:
            raise exc
        user_id = int(sub)  # sub is stored as string (JWT spec), cast back to int
    except JWTError:
        raise exc

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise exc
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended",
        )

    log.debug("AUTH  user_id=%d  role=%s  active=%s", user.id, user.role, user.is_active)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
