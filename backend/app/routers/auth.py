from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.email import generate_token, hash_token, send_verification_email
from app.limiter import limiter
from app.logger import get_logger
from app.models.email_verification import EmailVerification
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_VERIFY_TOKEN_TTL_HOURS = 24


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
