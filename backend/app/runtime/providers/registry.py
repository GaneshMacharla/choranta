from typing import Dict, Optional
from app.core.config import settings
from app.runtime.exceptions import ProviderUnavailable
from app.runtime.providers.stt import STTProvider
from app.runtime.providers.llm import LLMProvider
from app.runtime.providers.tts import TTSProvider
from app.runtime.providers.telephony import TelephonyProvider
from app.runtime.providers.mock.stt import MockSTTProvider
from app.runtime.providers.mock.llm import MockLLMProvider
from app.runtime.providers.mock.tts import MockTTSProvider
from app.runtime.providers.telephony.mock import MockTelephonyProvider
from app.runtime.providers.cartesia.stt import CartesiaSTTProvider
from app.runtime.providers.cartesia.tts import CartesiaTTSProvider
from app.runtime.providers.gemini.llm import GeminiLLMProvider
from app.runtime.providers.sarvam.llm import SarvamLLMProvider
from app.runtime.providers.sarvam.stt import SarvamSTTProvider
from app.runtime.providers.sarvam.tts import SarvamTTSProvider
from app.runtime.providers.telephony.exotel import ExotelTelephonyProvider
from app.runtime.providers.telephony.vobiz import VobizTelephonyProvider
from app.runtime.providers.messaging import MessagingProvider, MetaWhatsAppProvider, MockMessagingProvider


class ProviderRegistry:
    """
    Registry resolving STT, LLM, TTS, and Telephony providers by name.
    Supports development/test mock mode as well as real Cartesia, Gemini, Exotel and Vobiz integrations.
    """

    def __init__(self, mode: Optional[str] = None):
        requested_mode = (mode or settings.RUNTIME_MODE).strip().lower()
        if requested_mode == "provider":
            requested_mode = "real"
        if requested_mode not in ("mock", "real"):
            raise ValueError("ProviderRegistry mode must be 'mock' or 'real'.")
        self.mode = requested_mode
        self._stt_providers: Dict[str, STTProvider] = {}
        self._llm_providers: Dict[str, LLMProvider] = {}
        self._tts_providers: Dict[str, TTSProvider] = {}
        self._telephony_providers: Dict[str, TelephonyProvider] = {}
        self._messaging_providers: Dict[str, MessagingProvider] = {}

        self._register_default_providers()

    def _register_default_providers(self) -> None:
        # Always register mock providers under their explicit mock keys
        mock_stt = MockSTTProvider("mock_stt")
        self.register_stt("mock_stt", mock_stt)

        mock_llm = MockLLMProvider("mock_llm")
        self.register_llm("mock_llm", mock_llm)

        mock_tts = MockTTSProvider("mock_tts")
        self.register_tts("mock_tts", mock_tts)

        mock_telephony = MockTelephonyProvider("mock_telephony")
        self.register_telephony("mock_telephony", mock_telephony)

        if self.mode == "real":
            # Real provider mode
            self.register_stt("cartesia", CartesiaSTTProvider())
            self.register_tts("cartesia", CartesiaTTSProvider())
            self.register_llm("gemini", GeminiLLMProvider())
            self.register_llm("sarvam", SarvamLLMProvider())
            self.register_stt("sarvam", SarvamSTTProvider())
            self.register_tts("sarvam", SarvamTTSProvider())
            self.register_telephony("exotel", ExotelTelephonyProvider())
            self.register_telephony("vobiz", VobizTelephonyProvider())
            self.register_messaging("whatsapp", MetaWhatsAppProvider())
        else:
            # Mock mode: alias canonical provider names to mock implementations for fast local test execution
            self.register_stt("cartesia", MockSTTProvider("cartesia"))
            self.register_llm("gemini", MockLLMProvider("gemini"))
            self.register_llm("sarvam", MockLLMProvider("sarvam"))
            self.register_stt("sarvam", MockSTTProvider("sarvam"))
            self.register_tts("sarvam", MockTTSProvider("sarvam"))
            self.register_tts("cartesia", MockTTSProvider("cartesia"))
            self.register_telephony("exotel", MockTelephonyProvider("exotel"))
            self.register_telephony("vobiz", MockTelephonyProvider("vobiz"))
            self.register_messaging("whatsapp", MockMessagingProvider("whatsapp"))

    def enable_real_providers(self) -> None:
        """Switch to real external providers."""
        self.mode = "provider"
        self.register_stt("cartesia", CartesiaSTTProvider())
        self.register_tts("cartesia", CartesiaTTSProvider())
        self.register_llm("gemini", GeminiLLMProvider())
        self.register_llm("sarvam", SarvamLLMProvider())
        self.register_stt("sarvam", SarvamSTTProvider())
        self.register_tts("sarvam", SarvamTTSProvider())
        self.register_telephony("exotel", ExotelTelephonyProvider())
        self.register_telephony("vobiz", VobizTelephonyProvider())
        self.register_messaging("whatsapp", MetaWhatsAppProvider())

    def enable_mock_providers(self) -> None:
        """Switch to mock providers for test isolation."""
        self.mode = "mock"
        self.register_stt("cartesia", MockSTTProvider("cartesia"))
        self.register_llm("gemini", MockLLMProvider("gemini"))
        self.register_llm("sarvam", MockLLMProvider("sarvam"))
        self.register_stt("sarvam", MockSTTProvider("sarvam"))
        self.register_tts("sarvam", MockTTSProvider("sarvam"))
        self.register_tts("cartesia", MockTTSProvider("cartesia"))
        self.register_telephony("exotel", MockTelephonyProvider("exotel"))
        self.register_telephony("vobiz", MockTelephonyProvider("vobiz"))
        self.register_messaging("whatsapp", MockMessagingProvider("whatsapp"))

    def register_stt(self, name: str, provider: STTProvider) -> None:
        self._stt_providers[name.lower()] = provider

    def register_llm(self, name: str, provider: LLMProvider) -> None:
        self._llm_providers[name.lower()] = provider

    def register_tts(self, name: str, provider: TTSProvider) -> None:
        self._tts_providers[name.lower()] = provider

    def register_telephony(self, name: str, provider: TelephonyProvider) -> None:
        self._telephony_providers[name.lower()] = provider

    def register_messaging(self, name: str, provider: MessagingProvider) -> None:
        self._messaging_providers[name.lower()] = provider

    def get_stt(self, name: str) -> STTProvider:
        key = name.lower()
        if key not in self._stt_providers:
            raise ProviderUnavailable("STT", name)
        return self._stt_providers[key]

    def get_llm(self, name: str) -> LLMProvider:
        key = name.lower()
        if key not in self._llm_providers:
            raise ProviderUnavailable("LLM", name)
        return self._llm_providers[key]

    def get_tts(self, name: str) -> TTSProvider:
        key = name.lower()
        if key not in self._tts_providers:
            raise ProviderUnavailable("TTS", name)
        return self._tts_providers[key]

    def get_telephony(self, name: str) -> TelephonyProvider:
        key = name.lower()
        if key not in self._telephony_providers:
            raise ProviderUnavailable("Telephony", name)
        return self._telephony_providers[key]

    def get_messaging(self, name: str) -> MessagingProvider:
        key = name.lower()
        if key not in self._messaging_providers:
            raise ProviderUnavailable("Messaging", name)
        return self._messaging_providers[key]

    def has_stt(self, name: str) -> bool:
        return name.lower() in self._stt_providers

    def has_llm(self, name: str) -> bool:
        return name.lower() in self._llm_providers

    def has_tts(self, name: str) -> bool:
        return name.lower() in self._tts_providers


# Global default registry instance
default_registry = ProviderRegistry(mode=settings.RUNTIME_MODE)
