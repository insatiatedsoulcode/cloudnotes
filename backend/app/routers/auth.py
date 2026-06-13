from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_VERIFY_TOKEN_TTL_HOURS = 24
_RESET_TOKEN_TTL_SECONDS = 3600  # 1 hour


def _hash(password: str) -> str:
    return pwd_context.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _make_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    # JWT spec (RFC 7519) requires sub to be a string
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.SECRET_KEY, algorithm="HS256")


def _issue_verification(user_id: int, db: Session) -> str:
    """Invalidate old tokens, create a fresh one, and return the raw token to email."""
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
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Login uses OAuth2 form fields (username + password), not JSON.
    This is the OAuth2 password flow spec — 'username' field contains the email.
    FastAPI's Swagger UI /docs handles this automatically.
    """
    log.info("LOGIN  email=%s", form.username)
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not _verify(form.password, user.password_hash):
        log.warning("LOGIN  failed  email=%s", form.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _make_token(user.id)
    log.info("LOGIN  → id=%d  role=%s  token_issued=yes", user.id, user.role)
    return {"access_token": token}


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Consume a verification token and mark the account as verified."""
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

    Token is deleted from Redis immediately after use (single-use guarantee).
    Existing JWT sessions remain valid — F-07 (refresh tokens) will add
    session revocation on password change.
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

    # Single-use: burn the token immediately so the link cannot be reused
    redis.delete(f"pwd_reset:{token_hash}")

    log.info("RESET-PASSWORD  user_id=%d", user.id)
    return {"message": "Password reset successfully. You can now log in with your new password."}
