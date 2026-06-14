from datetime import datetime, timedelta

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.cache import get_redis
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.email import (
    generate_token,
    hash_token,
    send_password_reset_email,
    send_verification_email,
)
from app.limiter import limiter
from app.logger import get_logger
from app.models.email_verification import EmailVerification
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    SessionResponse,
    Token,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_VERIFY_TOKEN_TTL_HOURS = 24
_RESET_TOKEN_TTL_SECONDS = 3600  # 1 hour


# ── Password helpers ──────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return pwd_context.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT access token ──────────────────────────────────────────────────────────

def _make_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    # JWT spec (RFC 7519) requires sub to be a string
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.SECRET_KEY, algorithm="HS256")


# ── Refresh token helpers ─────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    # X-Forwarded-For is set by load balancers / reverse proxies in production.
    # The first IP in the comma-separated list is the original client.
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _issue_refresh_token(user_id: int, db: Session, request: Request) -> str:
    """Persist a new RefreshToken row and return the raw token to set in the cookie."""
    raw, hashed = generate_token()
    rt = RefreshToken(
        user_id=user_id,
        token_hash=hashed,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:500],
    )
    db.add(rt)
    db.commit()
    return raw


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Set an HTTP-only refresh token cookie.

    HTTP-only: JavaScript cannot read it → XSS cannot steal it.
    path=/api/auth: the cookie is only sent to the auth sub-tree,
                    never to /api/notes/ or other endpoints.
    secure=True only in production (HTTPS required); off in dev/test (HTTP).
    """
    response.set_cookie(
        "refresh_token",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV == "production",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path="/api/auth",
    )


def _revoke_all_refresh_tokens(user_id: int, db: Session) -> None:
    """Revoke every active refresh token for a user.

    Called on:
    - Token reuse detected (breach response — nuke all sessions)
    - Password reset (prevents attacker who has a refresh token from staying in)
    - Password change (same reason)
    """
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,  # noqa: E712
    ).update({"revoked": True})
    db.commit()


# ── Email verification helpers ────────────────────────────────────────────────

def _issue_verification(user_id: int, db: Session) -> str:
    """Invalidate old email-verification tokens, create a fresh one, return raw token."""
    db.query(EmailVerification).filter(
        EmailVerification.user_id == user_id,
        EmailVerification.used == False,  # noqa: E712
    ).update({"used": True})

    raw, hashed = generate_token()
    verification = EmailVerification(
        user_id=user_id,
        token_hash=hashed,
        expires_at=datetime.utcnow() + timedelta(hours=_VERIFY_TOKEN_TTL_HOURS),
    )
    db.add(verification)
    db.commit()
    return raw


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("3/minute")
def register(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    log.info("REGISTER  email=%s", data.email)
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=data.email, password_hash=_hash(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("REGISTER  → id=%d  role=%s", user.id, user.role)

    raw_token = _issue_verification(user.id, db)
    send_verification_email(to=user.email, token=raw_token)

    return user


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Login with email + password.  Returns a short-lived access token (JSON) and
    sets a long-lived refresh token in an HTTP-only cookie.

    OAuth2 password flow: 'username' field carries the email address.
    FastAPI Swagger UI (/docs) handles this automatically.
    """
    log.info("LOGIN  email=%s", form.username)
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not _verify(form.password, user.password_hash):
        log.warning("LOGIN failed  email=%s", form.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = _make_access_token(user.id)
    raw_refresh = _issue_refresh_token(user.id, db, request)
    _set_refresh_cookie(response, raw_refresh)

    log.info("LOGIN  → id=%d  role=%s  tokens_issued=yes", user.id, user.role)
    return {"access_token": access_token}


@router.post("/refresh", response_model=Token)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Rotate the refresh token and issue a new access token.

    Reads the refresh token from the HTTP-only cookie (never from a body field).
    On success: old token revoked, new token pair issued.
    On reuse of an already-revoked token: entire session family revoked (breach response).
    """
    raw = request.cookies.get("refresh_token")
    if not raw:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    token_hash = hash_token(raw)
    rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if rt is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if rt.revoked:
        # A revoked token is being replayed — possible theft.  Nuke all sessions.
        log.warning("REFRESH REUSE DETECTED  user_id=%d  → revoking all sessions", rt.user_id)
        _revoke_all_refresh_tokens(rt.user_id, db)
        response.delete_cookie("refresh_token", path="/api/auth")
        raise HTTPException(
            status_code=401,
            detail="Refresh token already used. All sessions have been revoked for your safety.",
        )

    if rt.expires_at < datetime.utcnow():
        rt.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired. Please log in again.")

    user = db.query(User).filter(User.id == rt.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account suspended")

    # Rotate: revoke the old token, issue a new pair
    rt.revoked = True
    db.commit()

    access_token = _make_access_token(user.id)
    raw_new = _issue_refresh_token(user.id, db, request)
    _set_refresh_cookie(response, raw_new)

    log.info("REFRESH  user_id=%d  → rotated", user.id)
    return {"access_token": access_token}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    True server-side logout: revoke the refresh token in DB and clear the cookie.

    The current access token remains valid until its 15-minute TTL expires —
    this is acceptable given the short window.  F-07 does not implement an
    access token blacklist (that would require a Redis lookup on every request).
    """
    raw = request.cookies.get("refresh_token")
    if raw:
        token_hash = hash_token(raw)
        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if rt and not rt.revoked:
            rt.revoked = True
            db.commit()
            log.info("LOGOUT  → refresh token revoked")

    response.delete_cookie("refresh_token", path="/api/auth")


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Consume an email verification token and mark the account as verified."""
    token_hash = hash_token(token)
    verification = db.query(EmailVerification).filter(
        EmailVerification.token_hash == token_hash,
        EmailVerification.used == False,  # noqa: E712
        EmailVerification.expires_at > datetime.utcnow(),
    ).first()

    if not verification:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    verification.used = True
    user = db.query(User).filter(User.id == verification.user_id).first()
    user.is_verified = True
    db.commit()

    log.info("VERIFY  user_id=%d  email=%s", user.id, user.email)
    return {"message": "Email verified successfully. You can now create notes."}


@router.post("/resend-verification")
@limiter.limit("1 per 5 minutes")
def resend_verification(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Issue a new verification token and resend the email. Rate-limited to 1 per 5 minutes."""
    if current_user.is_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")

    raw_token = _issue_verification(current_user.id, db)
    send_verification_email(to=current_user.email, token=raw_token)

    log.info("RESEND-VERIFY  user_id=%d", current_user.id)
    return {"message": "Verification email resent. Check your inbox."}


@router.post("/forgot-password")
@limiter.limit("3/hour")
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Send a password reset email.

    Always returns 200 regardless of whether the email is registered —
    this prevents user enumeration (attacker cannot learn which emails exist).
    """
    user = db.query(User).filter(User.email == data.email).first()
    if user:
        raw, hashed = generate_token()
        get_redis().setex(f"pwd_reset:{hashed}", _RESET_TOKEN_TTL_SECONDS, str(user.id))
        send_password_reset_email(to=user.email, token=raw)
        log.info("FORGOT-PASSWORD  user_id=%d  email=%s", user.id, user.email)
    else:
        log.info("FORGOT-PASSWORD  email=%s  not_found=true", data.email)

    return {"message": "If that email exists, a reset link has been sent"}


@router.post("/reset-password")
@limiter.limit("5/hour")
def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Consume a reset token and update the password.

    Revokes all refresh tokens on success so stolen sessions cannot persist
    after a password change.  Token is single-use (deleted from Redis immediately).
    """
    token_hash = hash_token(data.token)
    redis = get_redis()
    user_id_str = redis.get(f"pwd_reset:{token_hash}")

    if not user_id_str:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == int(user_id_str)).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.password_hash = _hash(data.new_password)
    db.commit()

    redis.delete(f"pwd_reset:{token_hash}")
    _revoke_all_refresh_tokens(user.id, db)

    log.info("RESET-PASSWORD  user_id=%d  → refresh tokens revoked", user.id)
    return {"message": "Password reset successfully. You can now log in with your new password."}


# ── Session management ────────────────────────────────────────────────────────

@router.get("/sessions", response_model=List[SessionResponse])
def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all active sessions for the current user.

    'Active' means: not revoked AND not past expires_at.
    is_current=True marks the session whose refresh token cookie is in this request,
    so a frontend can highlight "this device" without exposing token values.
    """
    current_cookie = request.cookies.get("refresh_token")
    current_hash = hash_token(current_cookie) if current_cookie else None

    rows = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.expires_at > datetime.utcnow(),
        )
        .order_by(RefreshToken.created_at.desc())
        .all()
    )

    return [
        SessionResponse(
            id=r.id,
            ip_address=r.ip_address,
            user_agent=r.user_agent,
            created_at=r.created_at,
            expires_at=r.expires_at,
            is_current=r.token_hash == current_hash,
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a single session by ID.  Users can only revoke their own sessions."""
    rt = db.query(RefreshToken).filter(
        RefreshToken.id == session_id,
        RefreshToken.user_id == current_user.id,
        RefreshToken.revoked == False,  # noqa: E712
    ).first()

    if not rt:
        raise HTTPException(status_code=404, detail="Session not found")

    rt.revoked = True
    db.commit()
    log.info("SESSION REVOKE  user_id=%d  session_id=%d", current_user.id, session_id)


@router.delete("/sessions", status_code=204)
def revoke_all_sessions(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout everywhere: revoke all active sessions and clear the current cookie."""
    _revoke_all_refresh_tokens(current_user.id, db)
    response.delete_cookie("refresh_token", path="/api/auth")
    log.info("SESSION REVOKE ALL  user_id=%d", current_user.id)
