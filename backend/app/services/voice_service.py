import io
import logging
import time
import wave
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.schemas.catalog import VoiceResponse
from app.runtime.providers.cartesia.tts import CartesiaTTSProvider, DEFAULT_CARTESIA_VOICE_ID

logger = logging.getLogger("choranta.services.voice")

# Curated fallback voices in case of offline/network limits - Prioritized for India
FALLBACK_CARTESIA_VOICES: List[Dict[str, Any]] = [
    {
        "id": "4459a9a5-69d6-4680-b970-e13dc51845b6",
        "name": "Siya",
        "gender": "feminine",
        "language": "hi",
        "description": "Breathes life into words with a gentle, expressive quality, perfect for engaging listeners with heartfelt narratives and clear communication.",
        "tagline": "Gentle & Expressive (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": True,
        "provider": "cartesia"
    },
    {
        "id": "cb9c954d-bcaa-43ed-82bf-aeb5e88a3cb5",
        "name": "Kabir",
        "gender": "masculine",
        "language": "hi",
        "description": "Offering a composed and structured delivery, this voice seamlessly connects information, perfect for detailed service updates and coordination.",
        "tagline": "Composed & Structured (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "e6b71342-48f1-4c70-a13a-d197b176ff24",
        "name": "Sana",
        "gender": "feminine",
        "language": "hi",
        "description": "With a precise yet friendly delivery, this voice clarifies options and resolves queries effectively.",
        "tagline": "Friendly Support (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "41e97793-a58d-40b7-8430-83465e186f94",
        "name": "Aryan",
        "gender": "masculine",
        "language": "en",
        "description": "This voice offers a calm and meticulous approach, perfect for ensuring accuracy and guiding through detailed processes.",
        "tagline": "Calm & Meticulous (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "998c6d1b-0bd0-4d27-bce7-ed030e3c9e6c",
        "name": "Sarthak",
        "gender": "masculine",
        "language": "en",
        "description": "Provides a confident and consistent vocal presence, ensuring clarity and build trust in any communication.",
        "tagline": "Confident & Trusted (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "0046dfd7-171b-4442-9eb7-0712fa712a7a",
        "name": "Smruti",
        "gender": "feminine",
        "language": "en",
        "description": "Her precise and articulate tone ensures accuracy, making this voice excellent for delivering complex information and detailed explanations.",
        "tagline": "Precise & Articulate (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "cc71692b-f326-499b-8f8f-90a415b4d3fb",
        "name": "Akash",
        "gender": "masculine",
        "language": "en",
        "description": "A composed and articulate tone ideal for delivering organized content, such as educational modules or detailed business briefings.",
        "tagline": "Organized & Articulate (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "37eb1575-353e-44f4-855d-894b4f003642",
        "name": "Alok",
        "gender": "masculine",
        "language": "en",
        "description": "Delivers information with precise clarity and a reassuring presence, ideal for guiding listeners through complex details.",
        "tagline": "Reassuring Presence (Indian)",
        "country": "IN",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
        "name": "Skylar",
        "gender": "feminine",
        "language": "en",
        "description": "Approachable American female ideal for customer care, reception, and healthcare support.",
        "tagline": "Friendly Support Specialist",
        "country": "US",
        "preview_url": "https://files.cartesia.ai/files/file_8Ksc9MiYHq3Qnvyy7Khja3/download?format=playback",
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "47c38ca4-5f35-497b-b1a3-415245fb35e1",
        "name": "Daniel",
        "gender": "masculine",
        "language": "en",
        "description": "Clear, crisp male voice with warm professional inflection for digital assistants.",
        "tagline": "Warm Executive",
        "country": "US",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "62ae83ad-4f6a-430b-af41-a9bede9286ca",
        "name": "Gemma",
        "gender": "feminine",
        "language": "en",
        "description": "Confident, emotive British female for premium hospitality, clinics, and concierge.",
        "tagline": "Polished & Articulate",
        "country": "GB",
        "preview_url": "https://files.cartesia.ai/files/file_cWMRVAVYkjjajuLCdarTf1/download?format=playback",
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "30894953-bcce-41fe-892c-15ce19c843ff",
        "name": "Parker",
        "gender": "masculine",
        "language": "en",
        "description": "Casual, supportive warmth for friendly front-desk calls and appointment scheduling.",
        "tagline": "Casual & Friendly",
        "country": "US",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "ef191366-f52f-447a-a398-ed8c0f2943a1",
        "name": "Archie",
        "gender": "masculine",
        "language": "en",
        "description": "Warm, conversational British male for casual service desks and hospitality.",
        "tagline": "Conversational British",
        "country": "GB",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        "name": "Jacqueline",
        "gender": "feminine",
        "language": "en",
        "description": "Confident, young adult female with high empathy for patient intake and wellness.",
        "tagline": "Empathetic Healthcare Guide",
        "country": "US",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "b24f41fd-00a3-4cd8-992a-a0c9f13f3ef1",
        "name": "Clive",
        "gender": "masculine",
        "language": "en",
        "description": "Composed and articulate mature male voice with dignified delivery.",
        "tagline": "Composed & Mature",
        "country": "GB",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "2a12b36c-7f9b-4c3a-9f7a-72731b15323a",
        "name": "Ella",
        "gender": "feminine",
        "language": "en",
        "description": "Approachable, bright presence for fast-paced customer service.",
        "tagline": "Bright & Energetic",
        "country": "US",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "12e85709-099c-480a-ba3e-875c41a9611a",
        "name": "Arlo",
        "gender": "masculine",
        "language": "en",
        "description": "Friendly, mid-toned Australian male voice with inviting warmth.",
        "tagline": "Australian Warmth",
        "country": "AU",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "630ed21c-2c5c-41cf-9d82-10a7fd668370",
        "name": "Corey",
        "gender": "masculine",
        "language": "en",
        "description": "Inviting, cheerful young adult male for sales and real estate inquiries.",
        "tagline": "Cheerful & Inviting",
        "country": "US",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    },
    {
        "id": "79a125e8-cd45-4c13-8a67-188112f4dd22",
        "name": "Brooke",
        "gender": "feminine",
        "language": "en",
        "description": "Smooth, professional female voice suited for luxury hotels and corporate concierge.",
        "tagline": "Smooth & Refined",
        "country": "US",
        "preview_url": None,
        "is_default": False,
        "provider": "cartesia"
    }
]


class CartesiaPreviewUnavailable(Exception):
    pass


class VoiceService:
    """
    Manages Cartesia voice catalog discovery, caching, and audio previews.
    """
    _cache: Optional[List[VoiceResponse]] = None
    _cache_time: float = 0.0
    _previews: Dict[tuple, bytes] = {}  # (voice, language, text) -> WAV
    _CACHE_TTL_SECONDS: float = 3600.0  # 1 hour

    @classmethod
    def list_cartesia_voices(
        cls,
        query: Optional[str] = None,
        gender: Optional[str] = None,
        language: Optional[str] = None
    ) -> List[VoiceResponse]:
        """
        Lists all voices available in the configured Cartesia workspace.
        Uses in-memory cache with fallback to curated defaults.
        """
        now = time.time()
        if cls._cache is None or (now - cls._cache_time) > cls._CACHE_TTL_SECONDS:
            cls._refresh_cache()

        voices = cls._cache or [VoiceResponse(**v) for v in FALLBACK_CARTESIA_VOICES]

        # Apply filtering
        if gender:
            gender_norm = gender.lower().strip()
            voices = [v for v in voices if (v.gender or "").lower() == gender_norm]

        if language:
            lang_norm = language.lower().strip()
            voices = [v for v in voices if (v.language or "").lower() == lang_norm]

        if query:
            q_norm = query.lower().strip()
            voices = [
                v for v in voices
                if q_norm in v.name.lower()
                or (v.description and q_norm in v.description.lower())
                or (v.tagline and q_norm in v.tagline.lower())
                or q_norm in v.id.lower()
            ]

        return voices

    @classmethod
    def _refresh_cache(cls) -> None:
        """Fetches latest voice list from Cartesia API."""
        try:
            api_key = settings.CARTESIA_API_KEY
            if not api_key or api_key.startswith("mock"):
                logger.info("Using curated fallback Cartesia voices (no production API key).")
                cls._cache = [VoiceResponse(**v) for v in FALLBACK_CARTESIA_VOICES]
                cls._cache_time = time.time()
                return

            import cartesia
            client = cartesia.Cartesia(api_key=api_key)
            page = client.voices.list(limit=100, expand=["preview_file_url"])

            results: List[VoiceResponse] = []
            for item in page.data:
                v_dict = item.model_dump() if hasattr(item, "model_dump") else item.__dict__
                vid = str(v_dict.get("id"))
                v_name = str(v_dict.get("name") or vid[:8])
                v_gender = v_dict.get("gender")
                v_lang = v_dict.get("language") or "en"
                v_desc = v_dict.get("description")
                v_tagline = v_dict.get("tagline")
                v_country = v_dict.get("country")
                v_preview = v_dict.get("preview_file_url")

                results.append(
                    VoiceResponse(
                        id=vid,
                        name=v_name,
                        gender=v_gender,
                        language=v_lang,
                        description=v_desc,
                        tagline=v_tagline,
                        country=v_country,
                        preview_url=v_preview,
                        is_default=(vid == DEFAULT_CARTESIA_VOICE_ID),
                        provider="cartesia"
                    )
                )

            if results:
                # Prioritize Indian voices at the top of the catalog for Choranta India focus
                results.sort(
                    key=lambda v: (
                        0 if ((v.country or "").upper() == "IN" or (v.language or "").lower() in ["hi", "te", "ta", "mr", "bn", "gu", "kn", "ml", "pa", "ur"]) else 1,
                        v.name
                    )
                )
                cls._cache = results
                cls._cache_time = time.time()
                logger.info(f"Successfully cached {len(results)} Cartesia voices from API (Indian voices prioritized).")
            else:
                cls._cache = [VoiceResponse(**v) for v in FALLBACK_CARTESIA_VOICES]
                cls._cache_time = time.time()
        except Exception as e:
            logger.warning(f"Failed to fetch Cartesia voices from API ({e}), using curated fallbacks.")
            cls._cache = [VoiceResponse(**v) for v in FALLBACK_CARTESIA_VOICES]
            cls._cache_time = time.time()

    @classmethod
    def get_voice_preview_wav(cls, voice_id: str, sample_text: Optional[str] = None, language: Optional[str] = None) -> bytes:
        """
        WAV preview of a Cartesia voice speaking the agent's language (the same sample sentences as the Sarvam
        previews). Cached per voice and language. Raises CartesiaPreviewUnavailable when Cartesia can't make it,
        e.g. the account is out of credits, instead of playing something that isn't the voice.
        """
        from app.services.sarvam_voices import PREVIEW_TEXTS, _preview_language

        lang = _preview_language(language)
        text = sample_text or PREVIEW_TEXTS[lang]
        key = (voice_id, lang, text)
        cached = cls._previews.get(key)
        if cached is not None:
            return cached
        try:
            tts = CartesiaTTSProvider(api_key=settings.CARTESIA_API_KEY)
            raw_pcm = tts.synthesize(text=text, voice_id=voice_id, speed=1.0, language=lang).audio_bytes
        except Exception as e:
            logger.warning(f"Cartesia preview failed for voice '{voice_id}': {type(e).__name__}: {e}")
            if "quota" in str(e).lower() or "402" in str(e):
                raise CartesiaPreviewUnavailable("The Cartesia account is out of credits; top it up to hear Cartesia voices.")
            raise CartesiaPreviewUnavailable("Couldn't generate the Cartesia preview right now. Try again in a moment.")
        if not raw_pcm:
            raise CartesiaPreviewUnavailable("Couldn't generate the Cartesia preview right now. Try again in a moment.")

        # Convert raw 16-bit 16kHz PCM to standard WAV format
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(16000)
            wf.writeframes(raw_pcm)
        cls._previews[key] = buf.getvalue()
        return cls._previews[key]
