"""
Encrypts secrets stored in the database (clients' WhatsApp access tokens) with Fernet.

Production must set WHATSAPP_ENCRYPTION_KEY to store any (generate one with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
Development without one derives a key from the JWT secret, so local data stays readable across restarts.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    key = (settings.WHATSAPP_ENCRYPTION_KEY or "").strip()
    if not key and (settings.ENVIRONMENT or "").strip().lower() == "production":
        raise ValueError("WHATSAPP_ENCRYPTION_KEY isn't set on the server, so secrets can't be stored.")
    if not key:
        seed = settings.JWT_SECRET_KEY or settings.SUPABASE_JWT_SECRET or "choranta-dev"
        key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    """The stored secret, or ValueError if it was encrypted with a different key."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored secret can't be decrypted with the current key.") from exc
