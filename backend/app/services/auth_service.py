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
        """
        Password login is a lockout backup for the initial platform admin only;
        everyone else signs in with Google.
        """
        normalized = (email or "").lower().strip()
        if normalized != (settings.INITIAL_ADMIN_EMAIL or "").lower().strip():
            raise AuthenticationException("Password login is disabled. Please use Sign in with Google.")

        user = self.user_repo.get_by_email(normalized)
        if not user:
            raise AuthenticationException("Invalid email or password.")

        if user.status != "ACTIVE":
            raise AuthenticationException("Internal account is inactive. Contact platform admin.")

        if not user.hashed_password or not verify_password(password, user.hashed_password):
            raise AuthenticationException("Invalid email or password.")

        return self.issue_token(user)

    def authenticate_google(self, credential: str) -> TokenResponse:
        """
        Verifies a Google Identity Services ID token and signs in the user with that verified email.
        A new email signs up as a client (its own client account and portal login) when
        CLIENT_SELF_SIGNUP is on; internal staff roles are only ever granted by invitation.
        """
        if not settings.GOOGLE_CLIENT_ID:
            raise AuthenticationException("Google Sign-In isn't configured on the server (GOOGLE_CLIENT_ID).")
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            claims = google_id_token.verify_oauth2_token(credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        except Exception:
            raise AuthenticationException("Google sign-in failed. Please try again.")

        if not claims.get("email") or not claims.get("email_verified"):
            raise AuthenticationException("Your Google account email isn't verified.")

        email = str(claims["email"]).lower().strip()
        user = self.user_repo.get_by_email(email)
        if not user:
            if not settings.CLIENT_SELF_SIGNUP:
                raise AuthenticationException(
                    f"{claims['email']} hasn't been invited to Choranta. Ask your administrator for access."
                )
            user = self._sign_up_client(email, (claims.get("name") or "").strip())
        if user.status != "ACTIVE":
            raise AuthenticationException("This account is inactive. Contact your administrator.")
        return self.issue_token(user)

    def _sign_up_client(self, email: str, name: str) -> User:
        """Creates a client account and its first portal login for a new Google user."""
        from app.models.billing import ClientUser
        from app.models.client import Client

        display_name = name or email.split("@")[0]
        client = Client(
            id=generate_unique_id("cli_"), name=display_name, business_type="OTHER",
            contact_name=display_name, contact_email=email, status="ACTIVE",
        )
        user = User(id=generate_unique_id("usr", 12), email=email, name=display_name, hashed_password=None,
                    role="CLIENT", status="ACTIVE")
        self.db.add_all([client, user])
        self.db.flush()
        self.db.add(ClientUser(user_id=user.id, client_id=client.id))
        self.db.commit()
        return user

    def issue_token(self, user: User) -> TokenResponse:
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
