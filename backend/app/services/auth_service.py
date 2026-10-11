from datetime import timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import verify_password, hash_password, create_access_token, generate_unique_id
from app.core.exceptions import AuthenticationException, NotFoundException
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse, UserResponse


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)

    def authenticate_user(self, email: str, password: str) -> TokenResponse:
        user = self.user_repo.get_by_email(email)
        if not user:
            raise AuthenticationException("Invalid email or password.")
        
        if user.status != "ACTIVE":
            raise AuthenticationException("Internal account is inactive. Contact platform admin.")

        if not user.hashed_password or not verify_password(password, user.hashed_password):
            raise AuthenticationException("Invalid email or password.")

        token = create_access_token(
            subject=user.id,
            claims={
                "email": user.email,
                "role": user.role,
                "name": user.name
            }
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserResponse.model_validate(user)
        )

    def get_user_by_id(self, user_id: str) -> UserResponse:
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundException("User", user_id)
        return UserResponse.model_validate(user)

    def seed_initial_admin(self) -> Optional[User]:
        """Ensure initial internal operations administrator exists."""
        existing = self.user_repo.get_by_email(settings.INITIAL_ADMIN_EMAIL)
        if not existing:
            admin_user = User(
                id=generate_unique_id("usr", 12),
                email=settings.INITIAL_ADMIN_EMAIL.lower().strip(),
                name=settings.INITIAL_ADMIN_NAME,
                hashed_password=hash_password(settings.INITIAL_ADMIN_PASSWORD),
                role="ADMIN",
                status="ACTIVE",
            )
            return self.user_repo.create(admin_user)
        return existing
