"""
Places outbound calls through the telephony carrier. Shared by the "dial" endpoint and the
campaign dispatcher, so both apply the same readiness, billing and caller-number rules.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.call import Call
from app.models.phone_number import PhoneNumber
from app.repositories.call_repository import CallRepository
from app.repositories.phone_number_repository import PhoneNumberRepository
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.runtime.providers.registry import default_registry
from app.runtime.readiness.checker import RuntimeReadinessChecker
from app.services import phone_numbers
from app.services.billing import check_call_allowed

logger = logging.getLogger("choranta.services.outbound_calls")


class OutboundCallError(Exception):
    """A call that can't be placed. `code` lets callers react (e.g. the dispatcher pauses on NO_BALANCE)."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# Successful readiness checks per agent version, reused briefly: each check costs several
# database round trips, and campaign / instant-lead dials repeat it for the same version
READINESS_TTL_S = 60.0
_ready_versions: Dict[Tuple[str, str], float] = {}


def _check_ready(db: Session, agent_id: str, agent_version_id: str) -> None:
    key = (agent_id, agent_version_id)
    checked_at = _ready_versions.get(key)
    if checked_at is not None and time.monotonic() - checked_at < READINESS_TTL_S:
        return
    readiness = RuntimeReadinessChecker(db, default_registry).check(agent_id, agent_version_id)
    if not readiness["ready"]:
        _ready_versions.pop(key, None)
        raise OutboundCallError("NOT_READY", "Agent is not ready for calls: " + "; ".join(readiness["errors"]))
    _ready_versions[key] = time.monotonic()


def with_webhook_token(url: str) -> str:
    secret = getattr(settings, "EXOTEL_WEBHOOK_SECRET", None)
    return f"{url}?{urlencode({'token': secret})}" if secret else url


def place_outbound_call(
    db: Session,
    *,
    destination_number: str,
    phone_number_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_version_id: Optional[str] = None,
    caller_id: Optional[str] = None,
    is_test: bool = False,
    flow_id: Optional[str] = None,
    custom_field: Optional[str] = None,
    variables: Optional[Dict[str, Any]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    caller_record: Optional[Any] = None,
    client_id: Optional[str] = None,
) -> Call:
    """
    Dials `destination_number` from a phone number (its assigned agent answers) or from an agent
    version (calling from the client's own number, or `caller_id` when given). Returns the Call record.

    Campaign dials pass `caller_record` (an already-validated number with id / phone_number / provider)
    and `client_id` to skip lookups, since every database round trip delays the call.
    """
    phone_record: Optional[PhoneNumber] = None
    if phone_number_id:
        phone_repo = PhoneNumberRepository(db)
        phone_record = phone_repo.get_by_id(phone_number_id) or phone_repo.get_by_e164(phone_number_id)
        if not phone_record:
            raise OutboundCallError("NOT_FOUND", f"Phone number '{phone_number_id}' not found.", 404)
        if not phone_record.agent_id or not phone_record.agent_version_id:
            raise OutboundCallError(
                "CONFIG", f"Phone number '{phone_record.phone_number}' is not assigned to an AI Employee."
            )
        if not is_test and (phone_record.status != "ACTIVE" or phone_numbers.blocked_reason(db, phone_record)):
            raise OutboundCallError("CALLER_UNAVAILABLE", f"Phone number '{phone_record.phone_number}' can't place calls right now.")
        agent_id, agent_version_id = phone_record.agent_id, phone_record.agent_version_id
        caller_number = phone_record.phone_number
        provider_name = phone_record.provider or "exotel"
    elif agent_id and agent_version_id:
        if is_test:
            # Test calls from the Tests step may use Choranta's own ExoPhone
            caller_number = caller_id or getattr(settings, "EXOTEL_CALLER_ID", None)
            if not caller_number:
                raise OutboundCallError(
                    "CONFIG", "No caller ID: set EXOTEL_CALLER_ID in backend/.env to your ExoPhone, or pass caller_id."
                )
        elif caller_record is not None:
            phone_record = caller_record
            caller_number = caller_record.phone_number
        else:
            # Live calls show the client's own number, bought from Choranta
            owner = db.get(Agent, agent_id)
            own_number = phone_numbers.client_caller_number(db, owner.client_id, caller_id) if owner else None
            if not own_number:
                raise OutboundCallError(
                    "CALLER_UNAVAILABLE",
                    "This client has no active phone number to call from. Buy a phone number to place calls."
                    if not caller_id else f"'{caller_id}' isn't one of this client's active numbers.",
                )
            phone_record = own_number
            caller_number = own_number.phone_number
        provider_name = "exotel"
    else:
        raise OutboundCallError("CONFIG", "Provide phone_number_id, or agent_id and agent_version_id.")

    _check_ready(db, agent_id, agent_version_id)
    if not client_id:
        client_id = db.get(Agent, agent_id).client_id

    allowed, block_reason, block_code = (True, None, None) if is_test else check_call_allowed(db, client_id)
    if not allowed:
        raise OutboundCallError(block_code or "NOT_ALLOWED", block_reason, 429 if block_code == "CONCURRENCY" else 402)

    # Exotel must reach this server when the customer answers; fail fast instead of placing a dead call
    base_url = (settings.TELEPHONY_BASE_URL or "").rstrip("/")
    if not base_url.startswith("https://") or any(h in base_url for h in ("localhost", "127.0.0.1")):
        raise OutboundCallError(
            "CONFIG", "TELEPHONY_BASE_URL must be a public https:// address Exotel can reach (e.g. your ngrok URL)."
        )

    flow_id = flow_id or getattr(settings, "EXOTEL_FLOW_ID", None)
    account_sid = getattr(settings, "EXOTEL_ACCOUNT_SID", None)
    if not flow_id or not account_sid:
        raise OutboundCallError("CONFIG", "EXOTEL_FLOW_ID and EXOTEL_ACCOUNT_SID must be configured.")
    flow_url = f"http://my.exotel.com/{account_sid}/exoml/start_voice/{flow_id}"
    status_callback_url = with_webhook_token(f"{base_url}/api/telephony/exotel/status")

    telephony_provider = default_registry.get_telephony(provider_name)
    try:
        call_result = telephony_provider.initiate_outbound_call(
            customer_number=destination_number,
            caller_id=caller_number,
            flow_url=flow_url,
            status_callback_url=status_callback_url,
            custom_field=custom_field or f"agent:{agent_id}"
        )
    except Exception as exc:
        logger.error(f"Failed to initiate outbound call: {exc}")
        raise OutboundCallError("CARRIER", f"Carrier error: {exc}", 502)

    exotel_call_obj = call_result.get("Call") or {}
    provider_call_id = exotel_call_obj.get("Sid") or generate_unique_id("call", 12)

    metadata = {
        "exotel_response": call_result,
        "custom_field": custom_field,
        "variables": variables or {},
        "is_test": is_test,
        **(extra_metadata or {}),
    }
    saved_call = CallRepository(db).create(Call(
        id=generate_unique_id("call", 10),
        client_id=client_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        phone_number_id=phone_record.id if phone_record else None,
        provider=provider_name,
        provider_call_id=provider_call_id,
        direction="OUTBOUND",
        caller_number=caller_number,
        destination_number=destination_number,
        status="INITIATED",
        started_at=datetime.now(timezone.utc),
        duration_seconds=0.0,
        metadata_=metadata,
    ))

    EventEmitter(db).emit(
        RuntimeEventType.CALL_INITIATED,
        session_id="",
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        client_id=client_id,
        payload={"call_id": saved_call.id, "direction": "OUTBOUND", "provider_call_id": provider_call_id}
    )
    return saved_call
