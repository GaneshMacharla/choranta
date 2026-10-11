from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_any_user
from app.models.user import User
from app.schemas.auth import GoogleLoginRequest, LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Password login (initial platform admin only, as a lockout backup)."""
    service = AuthService(db)
    return service.authenticate_user(payload.email, payload.password)


@router.post("/google", response_model=TokenResponse)
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)):
    """Sign in with a Google ID token; only invited (existing, active) users are accepted."""
    return AuthService(db).authenticate_google(payload.credential)


@router.get("/config")
def auth_config():
    """Public sign-in configuration for the login page."""
    from app.core.config import settings
    return {"google_client_id": settings.GOOGLE_CLIENT_ID or None}


@router.get("/me", response_model=UserResponse)
def get_current_profile(current_user: User = Depends(get_any_user)):
    """Return the authenticated user's profile (internal staff or client portal)."""
    return UserResponse.model_validate(current_user)
