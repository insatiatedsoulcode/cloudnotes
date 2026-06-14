"""
User self-service endpoints (F-04c).

GET  /api/users/me  — view own profile
PUT  /api/users/me  — change password (email change requires email verification — F-05)
DELETE /api/users/me — soft-delete: sets is_active=False, token still valid until expiry
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.logger import get_logger
from app.models.user import User
from app.routers.auth import _hash, _revoke_all_refresh_tokens, _verify
from app.schemas.user import UserProfile, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])
log = get_logger("users")


@router.get("/me", response_model=UserProfile)
def get_my_profile(current_user: User = Depends(get_current_user)):
    log.info("PROFILE GET  user_id=%d", current_user.id)
    return current_user


@router.put("/me", response_model=UserProfile)
def update_my_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log.info("PROFILE UPDATE  user_id=%d", current_user.id)
    if not _verify(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = _hash(data.new_password)
    db.commit()
    # Revoke all refresh tokens so sessions using the old password cannot persist
    _revoke_all_refresh_tokens(current_user.id, db)
    db.refresh(current_user)
    log.info("PROFILE UPDATE  user_id=%d  → password changed  refresh_tokens_revoked=yes", current_user.id)
    return current_user


@router.delete("/me", status_code=204)
def deactivate_my_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log.info("PROFILE DELETE  user_id=%d  → deactivating", current_user.id)
    current_user.is_active = False
    db.commit()
