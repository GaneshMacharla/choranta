import audioop
import logging
from typing import Any, Dict, Optional, Tuple
from app.runtime.providers.telephony.base import TelephonyProvider, InboundCallPayload

logger = logging.getLogger("choranta.telephony.browser")

# Browser test calls carry the agent's full 16kHz audio (16-bit mono PCM), so the chosen voice sounds the same
# as its preview in the voice picker instead of cut down to phone-line quality.
BROWSER_SAMPLE_RATE = 16000
CANONICAL_SAMPLE_RATE = 16000


class BrowserTelephonyProvider(TelephonyProvider):
    """
    Carrier for browser test calls over WebRTC: no phone network and no telephony charges.
    Only the audio conversion is used; audio travels over the WebRTC peer connection,
    so there are no webhooks or media-stream messages.
    """

    # 100ms frames, the same pacing as Exotel
    outbound_frame_bytes = BROWSER_SAMPLE_RATE // 10 * 2
    carrier_sample_rate = BROWSER_SAMPLE_RATE

    @property
    def provider_name(self) -> str:
        return "browser"

    @property
    def environment(self) -> str:
        return "development"

    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass

    def validate_webhook(self, request_url: str, params: Dict[str, Any], signature: str) -> bool:
        return False

    def parse_inbound_call_webhook(self, params: Dict[str, Any]) -> InboundCallPayload:
        raise NotImplementedError("Browser calls have no carrier webhooks.")

    def generate_connect_response(self, stream_url: str, call_sid: str, status_callback_url: Optional[str] = None) -> str:
        raise NotImplementedError("Browser calls have no carrier webhooks.")

    def generate_reject_response(self, message: Optional[str] = None) -> str:
        raise NotImplementedError("Browser calls have no carrier webhooks.")

    def parse_stream_start(self, data: Dict[str, Any]) -> Tuple[str, str]:
        raise NotImplementedError("Browser calls have no media-stream messages.")

    def build_media_message(self, stream_id: str, audio_bytes: bytes) -> str:
        raise NotImplementedError("Browser call audio is sent over WebRTC.")

    def build_clear_message(self, stream_id: str) -> str:
        raise NotImplementedError("Browser call audio is sent over WebRTC.")

    def normalize_audio_inbound(self, audio_chunk: bytes) -> bytes:
        """Browser caller audio to canonical 16kHz PCM16 (already 16kHz: passed through unchanged)."""
        if not audio_chunk:
            return b""
        try:
            if len(audio_chunk) % 2:
                audio_chunk = audio_chunk[:-1]
            if BROWSER_SAMPLE_RATE == CANONICAL_SAMPLE_RATE:
                return audio_chunk
            pcm16k, _ = audioop.ratecv(audio_chunk, 2, 1, BROWSER_SAMPLE_RATE, CANONICAL_SAMPLE_RATE, None)
            return pcm16k
        except Exception as e:
            logger.warning(f"Error normalizing browser audio: {e}")
            return b""

    def normalize_audio_outbound(self, pcm_bytes: bytes) -> bytes:
        """Canonical 16kHz PCM16 agent audio to browser audio (already 16kHz: passed through unchanged)."""
        if not pcm_bytes:
            return b""
        try:
            if len(pcm_bytes) % 2:
                pcm_bytes = pcm_bytes[:-1]
            if BROWSER_SAMPLE_RATE == CANONICAL_SAMPLE_RATE:
                return pcm_bytes
            converted, _ = audioop.ratecv(pcm_bytes, 2, 1, CANONICAL_SAMPLE_RATE, BROWSER_SAMPLE_RATE, None)
            return converted
        except Exception as e:
            logger.warning(f"Error normalizing agent audio for the browser: {e}")
            return b""
