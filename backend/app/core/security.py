import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import jwt
from app.core.config import settings
from app.core.exceptions import AuthenticationException


class ExpiredTokenException(AuthenticationException):
    def __init__(self, message: str = "Authentication token has expired."):
        super().__init__(message)


class InvalidTokenException(AuthenticationException):
    def __init__(self, message: str = "Invalid authentication token signature or format."):
        super().__init__(message)


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a cryptographically secure random salt."""
    salt = secrets.token_hex(16)
    iterations = 100_000
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations
    )
    return f"{salt}:{iterations}:{derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against salt:iterations:hex hash using constant-time comparison."""
    try:
        parts = hashed_password.split(":")
        if len(parts) != 3:
            return False
        salt, iterations_str, stored_hash = parts
        iterations = int(iterations_str)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations
        )
        return hmac.compare_digest(derived.hex(), stored_hash)
    except Exception:
        return False


def create_access_token(
    subject: str,
    claims: Optional[Dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Generate signed JWT access token."""
    secret = settings.SUPABASE_JWT_SECRET or settings.JWT_SECRET_KEY
    if not secret:
        raise RuntimeError("No JWT signing secret configured.")

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: Dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "aud": "authenticated",
    }
    if claims:
        to_encode.update(claims)

    encoded_jwt = jwt.encode(to_encode, secret, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_and_verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode JWT token against Supabase JWT Secret or configured JWT secret key.
    Enforces strict signature verification and expiration checking.
    """
    secret = settings.SUPABASE_JWT_SECRET or settings.JWT_SECRET_KEY
    if not secret:
        raise RuntimeError("No JWT verification secret configured.")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": False,  # Allow Supabase authenticated tokens as well as internal tokens
            }
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise ExpiredTokenException("Authentication token has expired.")
    except jwt.InvalidTokenError:
        raise InvalidTokenException("Invalid authentication token signature or malformed token.")


def generate_unique_id(prefix: str = "id", length: int = 12) -> str:
    """Generate non-sequential, cryptographically random identifier."""
    random_part = secrets.token_hex(length // 2)
    return f"{prefix}_{random_part}"
