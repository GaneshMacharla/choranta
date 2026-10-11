from typing import Optional

from app.core.config import settings

SARVAM_REST_BASE_URL = "https://api.sarvam.ai"


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
