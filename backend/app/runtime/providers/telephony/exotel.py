import audioop
import base64
import hmac
import json
import logging
import re
from typing import Any, Dict, Optional, Tuple
from app.core.config import settings
from app.runtime.providers.telephony.base import TelephonyProvider, InboundCallPayload

logger = logging.getLogger("choranta.runtime.telephony.exotel")

EXOTEL_SAMPLE_RATE = 8000
CANONICAL_SAMPLE_RATE = 16000


def normalize_exotel_number(number: str, default_country_code: str = "91") -> str:
    """
    Normalizes Exotel phone numbers to E.164.
    Exotel commonly sends national-format numbers (e.g. '09876543210' or '9876543210').
    """
    raw = (number or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return "+" + re.sub(r"\D", "", raw)

    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        return f"+{default_country_code}{digits[1:]}"
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"
    if digits.startswith(default_country_code) and len(digits) == 10 + len(default_country_code):
        return "+" + digits
    return "+" + digits if digits else ""


def format_exotel_dial_number(number: str) -> str:
    """Formats phone numbers for the Exotel Calls/connect API (prefixed with 0 for national numbers)."""
    digits = re.sub(r"\D", "", (number or "").strip())
    if len(digits) == 10:
        return f"0{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"0{digits[2:]}"
    if len(digits) == 11 and digits.startswith("0"):
        return digits
    return digits



class ExotelTelephonyProvider(TelephonyProvider):
    """
    Exotel Telephony adapter for Choranta.

    Calls are bridged with Exotel's Voicebot applet (AgentStream):
      1. The Voicebot applet's dynamic URL points at /api/telephony/exotel/inbound, which
         resolves routing and answers with JSON {"url": "wss://.../ws/telephony/exotel/media"}.
      2. Exotel opens the WebSocket and streams base64 raw/slin audio
         (16-bit little-endian linear PCM, 8kHz mono) using connected/start/media/stop events.

    Exotel does not sign webhooks, so requests are authenticated with a shared secret
    (EXOTEL_WEBHOOK_SECRET) passed as the `token` query parameter on every configured URL.
    """

    response_media_type = "application/json"
    # Exotel expects outbound media in multiples of 320 bytes; 3200 bytes = 100ms at 8kHz 16-bit.
    outbound_frame_bytes = 3200

    def __init__(
        self,
        account_sid: Optional[str] = None,
        api_key: Optional[str] = None,
        api_token: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        self._account_sid = account_sid or getattr(settings, "EXOTEL_ACCOUNT_SID", None)
        self._api_key = api_key or getattr(settings, "EXOTEL_API_KEY", None)
        self._api_token = api_token or getattr(settings, "EXOTEL_API_TOKEN", None)
        self._webhook_secret = webhook_secret or getattr(settings, "EXOTEL_WEBHOOK_SECRET", None)

    @property
    def provider_name(self) -> str:
        return "exotel"

    @property
    def environment(self) -> str:
        return "production"

    @property
    def webhook_secret(self) -> Optional[str]:
        return self._webhook_secret

    def initialize(self, config: Dict[str, Any]) -> None:
        self._account_sid = config.get("account_sid") or self._account_sid
        self._api_key = config.get("api_key") or self._api_key
        self._api_token = config.get("api_token") or self._api_token
        self._webhook_secret = config.get("webhook_secret") or self._webhook_secret

    def close(self) -> None:
        pass

    def validate_webhook(self, request_url: str, params: Dict[str, Any], signature: str) -> bool:
        """
        Validates the shared-secret token supplied with an Exotel webhook or media-stream connection.
        `signature` is the value of the `token` query parameter.
        """
        if not self._webhook_secret:
            if settings.ENVIRONMENT in ("development", "test"):
                logger.warning("Exotel webhook secret not configured; permitting webhook in development/test mode.")
                return True
            return False

        if not signature:
            return False
        return hmac.compare_digest(str(signature), str(self._webhook_secret))

    def parse_inbound_call_webhook(self, params: Dict[str, Any]) -> InboundCallPayload:
        """Parses Exotel applet webhook parameters (CallSid, CallFrom/From, CallTo/To)."""
        call_sid = params.get("CallSid") or params.get("call_sid") or ""
        caller = params.get("CallFrom") or params.get("From") or params.get("from") or ""
        dest = params.get("CallTo") or params.get("To") or params.get("to") or ""

        return InboundCallPayload(
            provider_call_id=call_sid,
            caller_number=normalize_exotel_number(caller),
            destination_number=normalize_exotel_number(dest),
            direction="INBOUND",
            provider="exotel",
            raw_params=params
        )

    def generate_connect_response(self, stream_url: str, call_sid: str, status_callback_url: Optional[str] = None) -> str:
        """
        Returns the Voicebot applet dynamic-URL response pointing Exotel at Choranta's media WebSocket.
        Recording and status callbacks are configured on the Exotel flow (Voicebot record option + Passthru applet).
        """
        return json.dumps({"url": stream_url})

    def generate_reject_response(self, message: Optional[str] = None) -> str:
        """
        Returns an empty stream URL so the Voicebot applet fails over to the next applet in the flow
        (configure a Greeting + Hangup there to play a rejection notice).
        """
        return json.dumps({"url": "", "error": message or "Call cannot be serviced."})

    def parse_stream_start(self, data: Dict[str, Any]) -> Tuple[str, str]:
        start_info = data.get("start", {}) or {}
        stream_sid = start_info.get("stream_sid") or data.get("stream_sid") or ""
        call_sid = start_info.get("call_sid") or ""
        return stream_sid, call_sid

    def build_media_message(self, stream_id: str, audio_bytes: bytes) -> str:
        return json.dumps({
            "event": "media",
            "stream_sid": stream_id,
            "media": {"payload": base64.b64encode(audio_bytes).decode("ascii")}
        })

    def build_clear_message(self, stream_id: str) -> str:
        return json.dumps({"event": "clear", "stream_sid": stream_id})

    def normalize_audio_inbound(self, audio_chunk: bytes) -> bytes:
        """Converts Exotel 8kHz mono 16-bit PCM audio to canonical Choranta 16kHz mono 16-bit PCM."""
        if not audio_chunk:
            return b""
        try:
            if len(audio_chunk) % 2:
                audio_chunk = audio_chunk[:-1]
            pcm16k, _ = audioop.ratecv(audio_chunk, 2, 1, EXOTEL_SAMPLE_RATE, CANONICAL_SAMPLE_RATE, None)
            return pcm16k
        except Exception as e:
            logger.warning(f"Error normalizing inbound audio: {e}")
            return b""

    def normalize_audio_outbound(self, pcm_bytes: bytes) -> bytes:
        """Converts Choranta 16kHz mono 16-bit PCM audio to Exotel 8kHz mono 16-bit PCM audio."""
        if not pcm_bytes:
            return b""
        try:
            if len(pcm_bytes) % 2:
                pcm_bytes = pcm_bytes[:-1]
            pcm8k, _ = audioop.ratecv(pcm_bytes, 2, 1, CANONICAL_SAMPLE_RATE, EXOTEL_SAMPLE_RATE, None)
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
        custom_field: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Triggers an outbound call connecting customer_number to flow_url upon answer.
        POST https://{EXOTEL_SUBDOMAIN}/v1/Accounts/{EXOTEL_ACCOUNT_SID}/Calls/connect.json
        """
        import httpx

        subdomain = getattr(settings, "EXOTEL_SUBDOMAIN", "api.exotel.com")
        account_sid = self._account_sid or getattr(settings, "EXOTEL_ACCOUNT_SID", None)
        api_key = self._api_key or getattr(settings, "EXOTEL_API_KEY", None)
        api_token = self._api_token or getattr(settings, "EXOTEL_API_TOKEN", None)

        if not account_sid or not api_key or not api_token:
            raise ValueError("Exotel credentials (EXOTEL_ACCOUNT_SID, EXOTEL_API_KEY, EXOTEL_API_TOKEN) are missing.")

        url = f"https://{subdomain}/v1/Accounts/{account_sid}/Calls/connect.json"
        dial_customer = format_exotel_dial_number(customer_number)
        dial_caller_id = format_exotel_dial_number(caller_id)

        form_data = {
            "From": dial_customer,
            "CallerId": dial_caller_id,
            "Url": flow_url,
            "CallType": "trans",
        }
        if status_callback_url:
            form_data["StatusCallback"] = status_callback_url
        if custom_field:
            form_data["CustomField"] = custom_field

        logger.info(f"Initiating Exotel outbound call: Customer={dial_customer}, CallerId={dial_caller_id}, Url={flow_url}")

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    url,
                    data=form_data,
                    auth=(api_key, api_token)
                )
                if resp.status_code not in (200, 201):
                    logger.error(f"Exotel outbound call failed ({resp.status_code}): {resp.text}")
                    try:
                        err_json = resp.json()
                        err_msg = err_json.get("RestException", {}).get("Message") or resp.text
                    except Exception:
                        err_msg = resp.text
                    raise RuntimeError(f"Exotel API error ({resp.status_code}): {err_msg}")
                return resp.json()
        except httpx.RequestError as exc:
            logger.error(f"Network error contacting Exotel: {exc}")
            raise RuntimeError(f"Failed to connect to Exotel API: {exc}") from exc

