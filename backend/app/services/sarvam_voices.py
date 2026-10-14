"""
Sarvam Bulbul v3 voices clients pick for a new AI employee, with short spoken previews.

Speaker ids from Sarvam's Bulbul v3 model docs (docs.sarvam.ai/api/getting-started/models/bulbul).
Previews are synthesized once per voice and kept in memory, so listening again costs nothing.
"""
import io
import logging
import threading
import wave
from typing import Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger("choranta.services.sarvam_voices")

# Bulbul v3 speakers and their gender, from Sarvam's "change the speaker voice" guide
FEMALE_VOICES = {
    "ritu", "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya", "roopa", "tanya", "shruti", "suhani",
    "kavitha", "rupali",
}
SARVAM_VOICES: List[str] = [
    "shubh", "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran", "kavya", "amit", "dev",
    "ishita", "shreya", "ratan", "varun", "manan", "sumit", "roopa", "kabir", "aayan", "ashutosh", "advait",
    "anand", "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani", "mohit", "kavitha",
    "rehan", "soham", "rupali",
]
# Sarvam's production tiers by critical error rate (1 = excellent, 2 = good, 3 = moderate); others are untiered
VOICE_TIERS: Dict[str, int] = {
    **{v: 1 for v in ("mani", "priya", "ishita", "varun")},
    **{v: 2 for v in ("roopa", "shubh", "pooja", "sunny", "ratan", "rehan", "ashutosh", "amit", "rahul")},
    **{v: 3 for v in ("aditya", "simran", "suhani", "shreya", "anand", "rupali", "neha", "ritu", "manan", "dev")},
}
# Sarvam's recommended speakers per language (male and female)
RECOMMENDED_BY_LANGUAGE: Dict[str, List[str]] = {
    "en": ["ratan", "ishita"],
    "hi": ["shubh", "ashutosh", "priya", "suhani"],
    "te": ["shubh", "ratan", "neha", "priya"],
    "kn": ["shubh", "ratan", "neha", "ishita"],
    "bn": ["rehan", "roopa", "suhani"],
    "ta": ["ratan", "rohan", "ishita", "ritu"],
    "od": ["shubh", "ritu", "pooja"],
    "ml": ["shubh", "pooja"],
    "mr": ["ratan", "priya", "ritu"],
    "pa": ["mani", "roopa", "suhani"],
    "gu": ["ratan", "priya", "ritu"],
}
VOICE_NOTES: Dict[str, str] = {
    "varun": "Deep, dramatic voice for suspense or characters; not a neutral voice for business calls.",
}
PREVIEW_TEXT = "Hello! Thank you for calling. I'm your AI employee, and I'm happy to help you today."
PREVIEW_LANGUAGE = "en-IN"
# Previews in the AI employee's own language, so a voice is heard the way callers will hear it
PREVIEW_TEXTS: Dict[str, str] = {
    "en": PREVIEW_TEXT,
    "hi": "नमस्ते! कॉल करने के लिए धन्यवाद। मैं आपकी AI सहायक हूँ, बताइए मैं आपकी क्या मदद कर सकती हूँ?",
    "te": "నమస్తే! కాల్ చేసినందుకు ధన్యవాదాలు. నేను మీ AI అసిస్టెంట్‌ని, ఈరోజు మీకు ఎలా సహాయం చేయగలను?",
    "ta": "வணக்கம்! அழைத்ததற்கு நன்றி. நான் உங்கள் AI உதவியாளர், இன்று உங்களுக்கு எப்படி உதவலாம்?",
    "kn": "ನಮಸ್ಕಾರ! ಕರೆ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ನಾನು ನಿಮ್ಮ AI ಸಹಾಯಕ, ಇಂದು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ?",
    "ml": "നമസ്കാരം! വിളിച്ചതിന് നന്ദി. ഞാൻ നിങ്ങളുടെ AI അസിസ്റ്റന്റ് ആണ്, ഇന്ന് ഞാൻ എങ്ങനെ സഹായിക്കണം?",
    "mr": "नमस्कार! कॉल केल्याबद्दल धन्यवाद. मी तुमची AI सहाय्यक आहे, आज मी तुम्हाला कशी मदत करू?",
    "bn": "নমস্কার! কল করার জন্য ধন্যবাদ। আমি আপনার AI সহকারী, আজ কীভাবে সাহায্য করতে পারি?",
    "gu": "નમસ્તે! કૉલ કરવા બદલ આભાર. હું તમારી AI સહાયક છું, આજે હું તમારી કેવી રીતે મદદ કરી શકું?",
}
SAMPLE_RATE = 16000

_previews: Dict[tuple, bytes] = {}
_lock = threading.Lock()


class VoicePreviewUnavailable(Exception):
    pass


def is_voice(voice_id: Optional[str]) -> bool:
    return (voice_id or "") in SARVAM_VOICES


def _base_language(language: Optional[str]) -> str:
    base = (language or "").split("-")[0].lower()
    return "od" if base == "or" else base


def list_voices(language: Optional[str] = None) -> List[Dict[str, object]]:
    """
    Voices with gender, Sarvam's quality tier and the languages Sarvam recommends them for. Ordered best first:
    voices recommended for `language` (when given), then by tier, then the rest.
    """
    voices = []
    for v in SARVAM_VOICES:
        voices.append({
            "id": v, "name": v.capitalize(), "provider": "sarvam", "is_default": v == settings.SARVAM_TTS_SPEAKER,
            "gender": "female" if v in FEMALE_VOICES else "male",
            "tier": VOICE_TIERS.get(v),
            "recommended_languages": [lang for lang, names in RECOMMENDED_BY_LANGUAGE.items() if v in names],
            "note": VOICE_NOTES.get(v),
        })
    wanted = RECOMMENDED_BY_LANGUAGE.get(_base_language(language), [])

    def rank(voice: Dict[str, object]) -> tuple:
        recommended = voice["id"] in wanted
        special = voice["id"] in VOICE_NOTES  # e.g. varun: never pushed to the top
        return (not recommended, special, voice["tier"] or 9, SARVAM_VOICES.index(voice["id"]))

    return sorted(voices, key=rank)


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _preview_language(language: Optional[str]) -> str:
    """Base language code with a preview sentence ('te-IN' -> 'te'); English otherwise."""
    base = (language or "en").split("-")[0].lower()
    return base if base in PREVIEW_TEXTS else "en"


def _synthesize(voice_id: str, language: str) -> bytes:
    from app.runtime.providers.sarvam.tts import SarvamTTSProvider
    result = SarvamTTSProvider(api_key=settings.SARVAM_API_KEY).synthesize(
        text=PREVIEW_TEXTS[language], voice_id=voice_id, speed=1.0,
        language=PREVIEW_LANGUAGE if language == "en" else language,
    )
    return result.audio_bytes


def preview_wav(voice_id: str, language: Optional[str] = None) -> bytes:
    """WAV preview of a Sarvam voice in the given language (English by default); raises
    VoicePreviewUnavailable if Sarvam can't be reached."""
    if not is_voice(voice_id):
        raise ValueError(f"Unknown voice '{voice_id}'.")
    lang = _preview_language(language)
    key = (voice_id, lang)
    with _lock:
        cached = _previews.get(key)
    if cached is not None:
        return cached
    if not settings.SARVAM_API_KEY:
        raise VoicePreviewUnavailable("Voice previews need a Sarvam API key.")
    try:
        pcm = _synthesize(voice_id, lang)
    except Exception as e:
        logger.warning(f"Sarvam preview failed for '{voice_id}': {type(e).__name__}: {e}")
        raise VoicePreviewUnavailable("Couldn't generate the preview right now. Try again in a moment.")
    if not pcm:
        raise VoicePreviewUnavailable("Couldn't generate the preview right now. Try again in a moment.")
    audio = _wav(pcm)
    with _lock:
        _previews[key] = audio
    return audio
