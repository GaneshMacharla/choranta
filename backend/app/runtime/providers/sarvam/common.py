from typing import Optional

from app.core.config import settings

SARVAM_REST_BASE_URL = "https://api.sarvam.ai"

# Connections to Sarvam are fast once open but occasionally slow to open (1-5 s TLS handshakes), so during calls:
# keep them open between turns (callers often pause longer than httpx's 5 s default), give up on a slow connect
# quickly and retry (a retry usually connects at once), and open them before the caller first speaks.
KEEPALIVE_S = 120.0
CONNECT_TIMEOUT_S = 2.0
CONNECT_RETRIES = 2


def sarvam_language(code: Optional[str], default: str = "en-IN") -> str:
    """Maps agent language codes ('hi', 'te', 'en', 'en-IN') to Sarvam's BCP-47 codes ('hi-IN', ...)."""
    if not code:
        return default
    code = code.strip()
    if code.lower() == "unknown":
        return "unknown"
    if "-" in code:
        base, region = code.split("-", 1)
        return f"{base.lower()}-{region.upper()}"
    return f"{code.lower()}-IN"


def sarvam_headers() -> dict:
    return {"api-subscription-key": settings.SARVAM_API_KEY or ""}
