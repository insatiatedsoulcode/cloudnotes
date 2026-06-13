from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.logger import get_logger
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash(password: str) -> str:
    return pwd_context.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _make_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    # JWT spec (RFC 7519) requires sub to be a string
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.SECRET_KEY, algorithm="HS256")


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
