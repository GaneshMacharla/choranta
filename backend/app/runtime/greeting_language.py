"""
Speaks the opening greeting in the agent's primary language.

The greeting is fixed text spoken word for word, so an English greeting (e.g. from a template) would open a
Telugu agent's call in English. When the primary language isn't English, the greeting is translated once with
Sarvam's translate API and cached; any failure keeps the original text so a call never waits on it.
"""
import logging
import re
from typing import Dict, Iterable, Optional, Tuple

import httpx

from app.core.config import settings
from app.runtime.providers.sarvam.common import SARVAM_REST_BASE_URL, sarvam_headers, sarvam_language

logger = logging.getLogger("choranta.runtime.greeting_language")

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "ml": "Malayalam",
    "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi", "od": "Odia", "or": "Odia",
}

_cache: Dict[Tuple[str, str], str] = {}


_SCRIPTS = (
    ("te", r"[ఀ-౿]"), ("hi", r"[ऀ-ॿ]"), ("ta", r"[஀-௿]"), ("kn", r"[ಀ-೿]"),
    ("ml", r"[ഀ-ൿ]"), ("bn", r"[ঀ-৿]"), ("gu", r"[઀-૿]"), ("pa", r"[਀-੿]"),
    ("od", r"[଀-୿]"),
)
# Everyday English words; romanised Telugu or Hindi ("naaku course kavali") has few of them
_ENGLISH_WORDS = frozenset(
    "i i'm im me my you your we our the a an is are was am be do does did can could will would should what when "
    "which where who why how this that it to of in on at for with and or but not no yes ok okay please want need "
    "know tell like have has get give about course courses fee fees batch batches class demo online weekend weekends "
    "weekday time timings start starts next thanks thank interested register talk person real human bot job".split()
)


def detect_language(text: str) -> Optional[str]:
    """The language of a caller's message: by script, or English when it's mostly everyday English words."""
    text = text or ""
    for code, pattern in _SCRIPTS:
        if re.search(pattern, text):
            return code
    words = re.findall(r"[a-z']+", text.lower())
    if len(words) >= 3 and sum(w in _ENGLISH_WORDS for w in words) / len(words) >= 0.35:
        return "en"
    return None


def language_name(code: str) -> str:
    base = (code or "en").split("-")[0].lower()
    return LANGUAGE_NAMES.get(base, code)


def is_english(code: str) -> bool:
    return (code or "en").split("-")[0].lower() == "en"


def localize_greeting(text: str, primary_language: str, keep: Iterable[str] = ()) -> str:
    """The greeting in the primary language; unchanged when it is English, already in that language, or
    translation is unavailable. Names in `keep` (e.g. the company) keep their original spelling."""
    text = (text or "").strip()
    if not text or is_english(primary_language):
        return text
    if settings.RUNTIME_MODE == "mock" or not settings.SARVAM_API_KEY:
        return text
    target = sarvam_language(primary_language)
    key = (text, target)
    if key in _cache:
        return _cache[key]
    try:
        resp = httpx.post(
            f"{SARVAM_REST_BASE_URL}/translate",
            headers=sarvam_headers(),
            json={"input": text, "source_language_code": "auto", "target_language_code": target,
                  "model": "mayura:v1", "mode": "modern-colloquial"},
            timeout=httpx.Timeout(4.0, connect=2.0),
        )
        resp.raise_for_status()
        data = resp.json()
        translated = (data.get("translated_text") or "").strip()
        # Already written in the target language (e.g. an operator's Telugu greeting): keep it as typed
        if data.get("source_language_code") == target or not translated:
            translated = text
        # The translator may re-case names ("KUNDHANASAI"), which TTS would spell out letter by letter
        for name in keep:
            if name and name.strip():
                translated = re.sub(re.escape(name.strip()), lambda _m, n=name.strip(): n, translated, flags=re.IGNORECASE)
    except Exception as exc:  # never block a call on the greeting
        logger.warning("Greeting translation to %s failed, using original: %s", target, exc)
        return text
    _cache[key] = translated
    return translated
