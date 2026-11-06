import base64
import json
from typing import Any, Dict, Optional, Tuple
from app.runtime.providers.telephony.base import TelephonyProvider, InboundCallPayload


class MockTelephonyProvider(TelephonyProvider):
    """
    Deterministic Mock Telephony provider for unit tests and local simulation.
    ENVIRONMENT: development/test
    """

    def __init__(self, name: str = "mock_telephony"):
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def environment(self) -> str:
        return "development/test"

    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass

    def validate_webhook(self, request_url: str, params: Dict[str, Any], signature: str) -> bool:
        return True

    def parse_inbound_call_webhook(self, params: Dict[str, Any]) -> InboundCallPayload:
        call_sid = params.get("CallSid") or params.get("call_sid") or "CA_mock_call"
        caller = params.get("CallFrom") or params.get("From") or params.get("from") or "+15550001111"
        dest = params.get("CallTo") or params.get("To") or params.get("to") or "+15559998888"

        return InboundCallPayload(
            provider_call_id=call_sid,
            caller_number=caller,
            destination_number=dest,
            direction="INBOUND",
            provider=self._name,
            raw_params=params
        )

    def generate_connect_response(self, stream_url: str, call_sid: str, status_callback_url: Optional[str] = None) -> str:
        return json.dumps({"url": stream_url})

    def generate_reject_response(self, message: Optional[str] = None) -> str:
        return json.dumps({"url": "", "error": message or "Call cannot be serviced."})

    def parse_stream_start(self, data: Dict[str, Any]) -> Tuple[str, str]:
        start_info = data.get("start", {}) or {}
        return start_info.get("stream_sid") or data.get("stream_sid") or "", start_info.get("call_sid") or ""

    def build_media_message(self, stream_id: str, audio_bytes: bytes) -> str:
        return json.dumps({
            "event": "media",
            "stream_sid": stream_id,
            "media": {"payload": base64.b64encode(audio_bytes).decode("ascii")}
        })

    def build_clear_message(self, stream_id: str) -> str:
        return json.dumps({"event": "clear", "stream_sid": stream_id})

    def normalize_audio_inbound(self, audio_chunk: bytes) -> bytes:
        # Mock passthrough or expansion
        return audio_chunk * 2 if audio_chunk else b""

    def normalize_audio_outbound(self, pcm_bytes: bytes) -> bytes:
        # Mock passthrough or truncation
        return pcm_bytes[: len(pcm_bytes) // 2] if pcm_bytes else b""

    def initiate_outbound_call(
        self,
        customer_number: str,
        caller_id: str,
        flow_url: str,
        status_callback_url: Optional[str] = None,
        custom_field: Optional[str] = None,
        max_duration_s: Optional[int] = None,
        ring_timeout_s: Optional[int] = None,
    ) -> Dict[str, Any]:
        import uuid
        call_sid = f"mock_call_{uuid.uuid4().hex[:12]}"
        return {
            "Call": {
                "Sid": call_sid,
                "From": customer_number,
                "To": caller_id,
                "Status": "in-progress",
            }
        }

