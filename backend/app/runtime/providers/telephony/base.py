from abc import abstractmethod
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel, Field
from app.runtime.providers.base import BaseProvider


class InboundCallPayload(BaseModel):
    provider_call_id: str
    caller_number: str
    destination_number: str
    direction: str = "INBOUND"
    provider: str = "exotel"
    raw_params: Dict[str, Any] = Field(default_factory=dict)


class TelephonyProvider(BaseProvider):
    """
    Abstract interface for Telephony providers (e.g. Exotel).
    Encapsulates webhook authentication, call-connect response generation,
    the media-stream WebSocket wire protocol, and bidirectional audio translation
    (PSTN 8kHz audio ↔ internal canonical 16kHz PCM16).
    """

    # Media type of the HTTP body returned by generate_connect_response / generate_reject_response
    response_media_type: str = "application/json"

    # Size in bytes of each outbound media frame sent to the carrier (0 = send chunks as produced)
    outbound_frame_bytes: int = 0
    # Sample rate of the carrier's 16-bit mono PCM audio, both directions (phone lines are 8kHz)
    carrier_sample_rate: int = 8000

    @abstractmethod
    def validate_webhook(self, request_url: str, params: Dict[str, Any], signature: str) -> bool:
        """Authenticates an incoming provider webhook / media-stream connection."""
        pass

    @abstractmethod
    def parse_inbound_call_webhook(self, params: Dict[str, Any]) -> InboundCallPayload:
        """Parses raw webhook parameters into canonical InboundCallPayload."""
        pass

    @abstractmethod
    def generate_connect_response(self, stream_url: str, call_sid: str, status_callback_url: Optional[str] = None) -> str:
        """Generates the webhook response that connects the call to the bidirectional media stream."""
        pass

    @abstractmethod
    def generate_reject_response(self, message: Optional[str] = None) -> str:
        """Generates the webhook response for a call that cannot be serviced."""
        pass

    @abstractmethod
    def parse_stream_start(self, data: Dict[str, Any]) -> Tuple[str, str]:
        """Extracts (stream_id, provider_call_id) from a media-stream 'start' event."""
        pass

    @abstractmethod
    def build_media_message(self, stream_id: str, audio_bytes: bytes) -> str:
        """Builds an outbound media-stream frame carrying telephony-format audio."""
        pass

    @abstractmethod
    def build_clear_message(self, stream_id: str) -> str:
        """Builds an outbound frame instructing the carrier to flush buffered playback (barge-in)."""
        pass

    @abstractmethod
    def normalize_audio_inbound(self, audio_chunk: bytes) -> bytes:
        """Converts incoming PSTN audio (e.g. 8kHz linear PCM) to canonical 16kHz 16-bit PCM."""
        pass

    @abstractmethod
    def normalize_audio_outbound(self, pcm_bytes: bytes) -> bytes:
        """Converts internal 16kHz 16-bit PCM audio to telephony format (e.g. 8kHz linear PCM)."""
        pass

    def initiate_outbound_call(
        self,
        customer_number: str,
        caller_id: str,
        flow_url: str,
        status_callback_url: Optional[str] = None,
        custom_field: Optional[str] = None
    ) -> Dict[str, Any]:
        """Initiates an outbound call connecting the customer to an AI voice flow."""
        raise NotImplementedError("Outbound calling not implemented for this provider.")

