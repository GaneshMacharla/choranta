import audioop
import base64
import hmac
import json
import logging
from typing import Any, Dict, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr
from app.core.config import settings
from app.runtime.providers.telephony.base import CarrierLimitError, TelephonyProvider, InboundCallPayload
from app.runtime.providers.telephony.exotel import normalize_exotel_number

logger = logging.getLogger("choranta.runtime.telephony.vobiz")

VOBIZ_SAMPLE_RATE = 8000
CANONICAL_SAMPLE_RATE = 16000
# Linear 16-bit PCM both ways, at the phone line's 8kHz (the same audio the Exotel stream carries)
VOBIZ_CONTENT_TYPE = "audio/x-l16"

# Vobiz hangup causes -> the call statuses apply_call_status understands
_HANGUP_CAUSE_STATUS = {
    "USER_BUSY": "busy",
    "CALL_REJECTED": "busy",
    "NO_ANSWER": "no-answer",
    "NO_USER_RESPONSE": "no-answer",
    "ORIGINATOR_CANCEL": "canceled",
}
_CALL_STATUS_ALIASES = {"timeout": "no-answer", "cancel": "canceled"}


def vobiz_call_status(params: Dict[str, Any]) -> Tuple[str, float]:
    """(call status, duration in seconds) from a Vobiz hangup callback."""
    try:
        duration = float(params.get("Duration") or params.get("BillDuration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    call_status = (params.get("CallStatus") or "").lower()
    call_status = _CALL_STATUS_ALIASES.get(call_status, call_status)
    if call_status:
        return call_status, duration
    cause = (params.get("HangupCause") or "").upper()
    if duration > 0:
        return "completed", duration
    return _HANGUP_CAUSE_STATUS.get(cause, "failed"), duration


class VobizTelephonyProvider(TelephonyProvider):
    """
    Vobiz Telephony adapter for Choranta.

    Calls are bridged with Vobiz's bidirectional audio stream:
      1. The call's Answer URL (/api/telephony/vobiz/answer) resolves routing and answers with XML
         <Stream bidirectional="true">wss://.../ws/telephony/vobiz/media</Stream>.
      2. Vobiz opens the WebSocket and streams base64 16-bit linear PCM (8kHz mono) in start/media
         events; we play audio back with playAudio and flush it on barge-in with clearAudio.

    Webhooks are authenticated with a shared secret (VOBIZ_WEBHOOK_SECRET) passed as the `token`
    query parameter on every URL we give Vobiz.
    """

    response_media_type = "application/xml"
    # 3200 bytes = 100ms at 8kHz 16-bit
    outbound_frame_bytes = 3200

    def __init__(
        self,
        auth_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        self._auth_id = auth_id or getattr(settings, "VOBIZ_AUTH_ID", None)
        self._auth_token = auth_token or getattr(settings, "VOBIZ_AUTH_TOKEN", None)
        self._webhook_secret = webhook_secret or getattr(settings, "VOBIZ_WEBHOOK_SECRET", None)

    @property
    def provider_name(self) -> str:
        return "vobiz"

    @property
    def environment(self) -> str:
        return "production"

    @property
    def webhook_secret(self) -> Optional[str]:
        return self._webhook_secret

    def initialize(self, config: Dict[str, Any]) -> None:
        self._auth_id = config.get("auth_id") or self._auth_id
        self._auth_token = config.get("auth_token") or self._auth_token
        self._webhook_secret = config.get("webhook_secret") or self._webhook_secret

    def close(self) -> None:
        pass

    def validate_webhook(self, request_url: str, params: Dict[str, Any], signature: str) -> bool:
        """Validates the shared-secret `token` query parameter (passed as `signature`)."""
        if not self._webhook_secret:
            if settings.ENVIRONMENT in ("development", "test"):
                logger.warning("Vobiz webhook secret not configured; permitting webhook in development/test mode.")
                return True
            return False

        if not signature:
            return False
        return hmac.compare_digest(str(signature), str(self._webhook_secret))

    def parse_inbound_call_webhook(self, params: Dict[str, Any]) -> InboundCallPayload:
        """Parses Vobiz Answer URL parameters (CallUUID, From, To)."""
        return InboundCallPayload(
            provider_call_id=params.get("CallUUID") or "",
            caller_number=normalize_exotel_number(params.get("From") or ""),
            destination_number=normalize_exotel_number(params.get("To") or ""),
            direction="INBOUND",
            provider="vobiz",
            raw_params=params
        )

    def generate_connect_response(self, stream_url: str, call_sid: str, status_callback_url: Optional[str] = None) -> str:
        """
        Answers with a bidirectional stream to Choranta's media WebSocket. keepCallAlive holds the call on
        the stream; when we close it (the agent hung up) the call moves on to <Hangup/>.
        """
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n<Response>'
            f'<Stream bidirectional="true" keepCallAlive="true" audioTrack="inbound" '
            f'contentType={quoteattr(f"{VOBIZ_CONTENT_TYPE};rate={VOBIZ_SAMPLE_RATE}")}>'
            f'{escape(stream_url)}</Stream><Hangup/></Response>'
        )

    def generate_reject_response(self, message: Optional[str] = None) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n<Response>'
            f'<Speak>{escape(message or "This call cannot be serviced.")}</Speak><Hangup/></Response>'
        )

    def parse_stream_start(self, data: Dict[str, Any]) -> Tuple[str, str]:
        start_info = data.get("start", {}) or {}
        stream_id = data.get("streamId") or start_info.get("streamId") or ""
        call_uuid = (data.get("callId") or start_info.get("callId") or start_info.get("callUUID")
                     or data.get("CallUUID") or "")
        return stream_id, call_uuid

    def build_media_message(self, stream_id: str, audio_bytes: bytes) -> str:
        return json.dumps({
            "event": "playAudio",
            "streamId": stream_id,
            "media": {
                "contentType": VOBIZ_CONTENT_TYPE,
                "sampleRate": VOBIZ_SAMPLE_RATE,
                "payload": base64.b64encode(audio_bytes).decode("ascii"),
            }
        })

    def build_clear_message(self, stream_id: str) -> str:
        return json.dumps({"event": "clearAudio", "streamId": stream_id})

    def normalize_audio_inbound(self, audio_chunk: bytes) -> bytes:
        """Converts Vobiz 8kHz mono 16-bit PCM audio to canonical Choranta 16kHz mono 16-bit PCM."""
        if not audio_chunk:
            return b""
        try:
            if len(audio_chunk) % 2:
                audio_chunk = audio_chunk[:-1]
            pcm16k, _ = audioop.ratecv(audio_chunk, 2, 1, VOBIZ_SAMPLE_RATE, CANONICAL_SAMPLE_RATE, None)
            return pcm16k
        except Exception as e:
            logger.warning(f"Error normalizing inbound audio: {e}")
            return b""

    def normalize_audio_outbound(self, pcm_bytes: bytes) -> bytes:
        """Converts Choranta 16kHz mono 16-bit PCM audio to Vobiz 8kHz mono 16-bit PCM audio."""
        if not pcm_bytes:
            return b""
        try:
            if len(pcm_bytes) % 2:
                pcm_bytes = pcm_bytes[:-1]
            pcm8k, _ = audioop.ratecv(pcm_bytes, 2, 1, CANONICAL_SAMPLE_RATE, VOBIZ_SAMPLE_RATE, None)
            return pcm8k
        except Exception as e:
            logger.warning(f"Error normalizing outbound audio: {e}")
            return b""

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
        """
        Dials customer_number from caller_id; Vobiz fetches flow_url (our Answer URL) once they pick up.
        POST {VOBIZ_API_BASE}/Account/{VOBIZ_AUTH_ID}/Call/
        Raises CarrierLimitError when Vobiz answers 429 (the account's concurrent-call or CPS limit).
        """
        import httpx

        api_base = getattr(settings, "VOBIZ_API_BASE", "https://api.vobiz.ai/api/v1").rstrip("/")
        auth_id = self._auth_id or getattr(settings, "VOBIZ_AUTH_ID", None)
        auth_token = self._auth_token or getattr(settings, "VOBIZ_AUTH_TOKEN", None)
        if not auth_id or not auth_token:
            raise ValueError("Vobiz credentials (VOBIZ_AUTH_ID, VOBIZ_AUTH_TOKEN) are missing.")

        body = {
            "from": normalize_exotel_number(caller_id),
            "to": normalize_exotel_number(customer_number),
            "answer_url": flow_url,
            "answer_method": "POST",
        }
        if status_callback_url:
            body["hangup_url"] = status_callback_url
            body["hangup_method"] = "POST"
        if max_duration_s:
            body["time_limit"] = int(max_duration_s)  # Vobiz's default is 4 hours
        if ring_timeout_s:
            body["hangup_on_ring"] = int(ring_timeout_s)

        logger.info(f"Initiating Vobiz outbound call: To={body['to']}, From={body['from']}")
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{api_base}/Account/{auth_id}/Call/",
                    json=body,
                    headers={"X-Auth-ID": auth_id, "X-Auth-Token": auth_token},
                )
        except httpx.RequestError as exc:
            logger.error(f"Network error contacting Vobiz: {exc}")
            raise RuntimeError(f"Failed to connect to Vobiz API: {exc}") from exc
        if resp.status_code == 429:
            logger.warning(f"Vobiz refused the call at the account's limit: {resp.text}")
            raise CarrierLimitError(f"Vobiz is at the account's call limit: {resp.text}")
        if resp.status_code not in (200, 201, 202):
            logger.error(f"Vobiz outbound call failed ({resp.status_code}): {resp.text}")
            try:
                err_msg = resp.json().get("error") or resp.json().get("message") or resp.text
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"Vobiz API error ({resp.status_code}): {err_msg}")
        return resp.json()

    def outbound_call_id(self, result: Dict[str, Any]) -> Optional[str]:
        # The request's id until the call is answered; the Answer URL then swaps in the CallUUID
        return result.get("call_uuid") or result.get("request_uuid")
