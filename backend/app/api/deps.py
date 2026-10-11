import threading
import time
from typing import Dict, Generator, Optional, Tuple
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import decode_and_verify_token, ExpiredTokenException, InvalidTokenException
from app.core.config import settings
from app.models.user import User
from app.repositories.user_repository import UserRepository

security_scheme = HTTPBearer(auto_error=False)

# Short-lived cache of verified ACTIVE users keyed by token, so hot paths (e.g. chat turns)
# don't pay a remote database round-trip on every request. A deactivation or role change
# takes effect within USER_CACHE_TTL_SECONDS.
USER_CACHE_TTL_SECONDS = 30.0
_user_cache: Dict[str, Tuple[float, Dict[str, object]]] = {}
_user_cache_lock = threading.Lock()
_USER_FIELDS = ("id", "email", "name", "role", "status", "created_at", "updated_at")


def _cached_user(token: str) -> Optional[User]:
    if settings.ENVIRONMENT == "test":
        return None
    with _user_cache_lock:
        entry = _user_cache.get(token)
        if not entry:
            return None
        expires_at, fields = entry
        if expires_at <= time.monotonic():
            _user_cache.pop(token, None)
            return None
    # Detached copy: callers only read identity/role fields
    return User(**fields)


def _cache_user(token: str, user: User) -> None:
    if settings.ENVIRONMENT == "test":
        return
    fields = {f: getattr(user, f) for f in _USER_FIELDS}
    with _user_cache_lock:
        if len(_user_cache) > 1000:
            _user_cache.clear()
        _user_cache[token] = (time.monotonic() + USER_CACHE_TTL_SECONDS, fields)


def _verify_token_and_get_user(token: str, db: Session) -> User:
    try:
        payload = decode_and_verify_token(token)
    except ExpiredTokenException as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenException as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed. Unable to verify credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    cached = _cached_user(token)
    if cached is not None:
        return cached

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token: missing subject identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(db)
    # Check by primary ID (or Supabase Auth UID)
    user = user_repo.get_by_id(user_id)
    # Fallback to email claim if ID was mapped differently
    if not user and "email" in payload:
        user = user_repo.get_by_email(payload["email"])

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found on Choranta platform.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deactivated. Operational access denied.",
        )

    _cache_user(token, user)
    return user


def get_current_user_from_header_or_query(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
) -> User:
    """
    Authenticate request via Bearer header or token query parameter.
    Useful for media endpoints like audio streams where HTML5 tags cannot pass headers.
    """
    raw_token: Optional[str] = None
    if credentials and credentials.credentials:
        raw_token = credentials.credentials.strip()
    elif token:
        raw_token = token.strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required. Please provide a valid Bearer token or token query parameter.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _internal_only(_verify_token_and_get_user(raw_token, db))


def _internal_only(user: User) -> User:
    """Client portal logins can never reach internal (studio) APIs."""
    if user.role == "CLIENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: client accounts can only use the client portal.",
        )
    return user


def get_any_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Authenticated user of any role (internal staff or client portal)."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _verify_token_and_get_user(credentials.credentials.strip(), db)


def get_current_user(user: User = Depends(get_any_user)) -> User:
    """
    Authenticated internal user (ADMIN or OPERATOR). Enforces expiration, signature integrity,
    active account, and rejects client portal accounts.
    """
    return _internal_only(user)


def require_client_user(user: User = Depends(get_any_user), db: Session = Depends(get_db)) -> Tuple[User, str]:
    """Client portal access: returns the user and the one client whose data they may see."""
    from app.models.billing import ClientUser

    if user.role != "CLIENT":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The client portal is for client accounts.")
    link = db.get(ClientUser, user.id)
    if not link:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account isn't linked to a client.")
    return user, link.client_id


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Authorize access strictly for ADMIN role."""
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Administrator privileges required for this action."
        )
    return current_user


def require_operator(current_user: User = Depends(get_current_user)) -> User:
    """Authorize access for OPERATOR or ADMIN roles."""
    if current_user.role not in ("OPERATOR", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Operational access required."
        )
    return current_user
