"""
Browser test calls over WebRTC: talk to an AI Employee from the browser with no phone network
and no telephony charges.

The call runs through the same TelephonyMediaSession as a real phone call (endpointing, streamed
replies, fillers, barge-in, call limits, recording, quality stats), with the browser as the carrier:
caller audio arrives on the peer connection's audio track and the agent's audio goes back on ours,
both as 16kHz audio. Each call is a Call record marked as a test, so it shows up in the
call logs but is never billed.
"""
import asyncio
import fractions
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

import av
from aiortc import MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_client_user, require_operator
from app.core.config import settings
from app.core.security import generate_unique_id
from app.db.session import SessionLocal, get_db
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.user import User
from app.repositories.call_repository import CallRepository
from app.runtime.context import TEST_CALL_PHONE
from app.runtime.events.types import RuntimeEventType
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony.browser import BROWSER_SAMPLE_RATE, BrowserTelephonyProvider
from app.runtime.runtime import AgentRuntime
from app.runtime.telephony.session import TelephonyMediaSession
from app.services import agent_requests, billing

logger = logging.getLogger("choranta.runtime.webrtc")

router = APIRouter(prefix="/telephony/browser-calls", tags=["Browser Test Calls (WebRTC)"])

# 20ms of browser audio (16-bit mono)
FRAME_SAMPLES = BROWSER_SAMPLE_RATE // 50
FRAME_BYTES = FRAME_SAMPLES * 2

# Live browser calls by call id
active_browser_calls: Dict[str, "BrowserCall"] = {}


class BrowserCallRequest(BaseModel):
    agent_id: str
    agent_version_id: str
    sdp: str = Field(..., description="The browser's SDP offer (with ICE candidates gathered)")
    type: str = "offer"
    user_name: Optional[str] = Field(None, max_length=120, description="Test caller's name (user_name)")
    company_name: Optional[str] = Field(None, max_length=200)


class BrowserCallResponse(BaseModel):
    call_id: str
    runtime_session_id: str
    sdp: str
    type: str


class AgentAudioTrack(MediaStreamTrack):
    """The agent's voice to the browser: buffered phone-line audio played out in real time, 20ms per frame."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._buffer = bytearray()
        self._start: Optional[float] = None
        self._pts = 0

    def write(self, pcm: bytes) -> None:
        self._buffer.extend(pcm)

    def clear(self) -> None:
        self._buffer.clear()

    async def recv(self) -> av.AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        if self._start is None:
            self._start = time.monotonic()
        else:
            self._pts += FRAME_SAMPLES
            wait = self._start + self._pts / BROWSER_SAMPLE_RATE - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)

        data = bytes(self._buffer[:FRAME_BYTES])
        del self._buffer[:FRAME_BYTES]
        if len(data) < FRAME_BYTES:
            data += b"\x00" * (FRAME_BYTES - len(data))

        frame = av.AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.planes[0].update(data)
        frame.sample_rate = BROWSER_SAMPLE_RATE
        frame.time_base = fractions.Fraction(1, BROWSER_SAMPLE_RATE)
        frame.pts = self._pts
        return frame


# Events forwarded live to the browser's data channel (the full record is in the call log)
_LIVE_EVENTS = {
    RuntimeEventType.USER_TRANSCRIPT_FINAL: "caller_text",
    RuntimeEventType.ASSISTANT_RESPONSE: "agent_text",
    RuntimeEventType.TTS_STARTED: "agent_speaking",
    RuntimeEventType.ASSISTANT_INTERRUPTED: "interrupted",
    RuntimeEventType.TOOL_CALL_STARTED: "tool_started",
}


class BrowserMediaSession(TelephonyMediaSession):
    """A phone call session whose carrier is a WebRTC peer connection instead of a carrier media stream."""

    def __init__(self, call_record: Call, db: Session, track: AgentAudioTrack,
                 notify: Callable[[Dict[str, Any]], None], on_hang_up: Callable[[str], None]):
        super().__init__(
            websocket=None,
            call_record=call_record,
            stream_sid=call_record.provider_call_id,
            db=db,
            telephony_provider=BrowserTelephonyProvider(),
        )
        self._track = track
        self._notify = notify
        self._on_hang_up = on_hang_up

    async def _send_carrier_audio(self, frame: bytes) -> None:
        self._track.write(frame)

    async def _clear_carrier_playback(self) -> None:
        self._track.clear()

    async def _disconnect_carrier(self) -> None:
        # Called from inside the agent's turn, so the call is ended from a separate task
        self._on_hang_up(self._end_reason or "agent_ended")

    def _emit(self, event_type: RuntimeEventType, payload: Dict[str, Any]) -> None:
        super()._emit(event_type, payload)
        kind = _LIVE_EVENTS.get(event_type)
        if kind:
            self._notify({"type": kind, **{k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool)) or v is None}})


class BrowserCall:
    """One browser test call: the peer connection, its phone session and the database session it uses."""

    def __init__(self, call_id: str,
                 on_end: Optional[Callable[[Session, str, Optional[float]], None]] = None):
        self.call_id = call_id
        # Told how the call ended: the reason, and how long it was connected (None = never connected)
        self._on_end = on_end
        self._connected_at: Optional[float] = None
        self.db = SessionLocal()
        self.track = AgentAudioTrack()
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]))
        self.channel = None
        self._channel_ready = False  # the browser said hello: its end of the data channel is open
        self._unsent: list = []
        self.session: Optional[BrowserMediaSession] = None
        self._caller_audio: Optional[asyncio.Task] = None
        self._started = False
        self._ended = False

    def notify(self, message: Dict[str, Any]) -> None:
        if not self._channel_ready or self.channel.readyState != "open":
            self._unsent.append(message)
            return
        try:
            self.channel.send(json.dumps(message, default=str))
        except Exception as e:
            logger.debug(f"Browser call {self.call_id}: data channel send failed: {e}")

    def _flush_unsent(self) -> None:
        unsent, self._unsent = self._unsent, []
        for message in unsent:
            self.notify(message)

    async def connect(self, offer: RTCSessionDescription) -> RTCSessionDescription:
        call_record = self.db.get(Call, self.call_id)
        self.session = BrowserMediaSession(call_record, self.db, self.track, self.notify, self.hang_up)
        self.pc.addTrack(self.track)

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.channel = channel

            @channel.on("message")
            def on_message(raw):
                try:
                    kind = json.loads(raw).get("type")
                except Exception:
                    return
                if kind == "hello":
                    self._channel_ready = True
                    self._flush_unsent()
                elif kind == "hangup":
                    self.hang_up("caller_hangup")

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "audio" and self._caller_audio is None:
                self._caller_audio = asyncio.create_task(self._pump_caller_audio(track))

        @self.pc.on("connectionstatechange")
        async def on_state():
            state = self.pc.connectionState
            logger.info(f"Browser call {self.call_id}: WebRTC {state}.")
            if state == "connected" and not self._started:
                self._started = True
                self._connected_at = time.monotonic()
                await self.session.initialize()  # plays the greeting
                self.notify({"type": "connected", "call_id": self.call_id})
            elif state in ("failed", "closed"):
                self.hang_up("caller_hangup" if state == "closed" else "connection_failed")

        await self.pc.setRemoteDescription(offer)
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        return self.pc.localDescription

    async def _pump_caller_audio(self, track) -> None:
        """Browser microphone (Opus, 48kHz) to 16kHz PCM frames for the call session."""
        resampler = av.AudioResampler(format="s16", layout="mono", rate=BROWSER_SAMPLE_RATE)
        try:
            while True:
                frame = await track.recv()
                if not self._started or self._ended:
                    continue
                for pcm in resampler.resample(frame):
                    await self.session.handle_carrier_audio(pcm.to_ndarray().tobytes())
        except MediaStreamError:
            pass
        except Exception as e:
            logger.warning(f"Browser call {self.call_id}: caller audio stopped: {type(e).__name__}: {e}")

    def hang_up(self, reason: str) -> None:
        if not self._ended:
            asyncio.create_task(self.end(reason))

    async def end(self, reason: str) -> None:
        if self._ended:
            return
        self._ended = True
        active_browser_calls.pop(self.call_id, None)
        self.notify({"type": "call_ended", "reason": reason})
        try:
            if self.session and self._started:
                await self.session.close(reason=reason)
            elif self.session:
                # Never connected: close the call record without running the session
                call_record = self.db.get(Call, self.call_id)
                if call_record and call_record.status not in ("COMPLETED", "FAILED"):
                    call_record.status = "FAILED"
                    call_record.ended_at = datetime.now(timezone.utc)
                    call_record.termination_reason = reason
                    self.db.commit()
                if call_record and call_record.runtime_session_id:
                    try:
                        AgentRuntime(self.db, registry=default_registry).end_session(call_record.runtime_session_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Browser call {self.call_id}: error ending the call: {type(e).__name__}: {e}")
        finally:
            if self._caller_audio and not self._caller_audio.done():
                self._caller_audio.cancel()
            try:
                await self.pc.close()
            except Exception:
                pass
            if self._on_end:
                connected = time.monotonic() - self._connected_at if self._connected_at is not None else None
                try:
                    self.db.rollback()
                    self._on_end(self.db, reason, connected)
                except Exception as e:
                    logger.error(f"Browser call {self.call_id}: end hook failed: {type(e).__name__}: {e}")
            self.db.close()
            logger.info(f"Browser call {self.call_id} ended ({reason}).")


def _create_call_record(db: Session, req: BrowserCallRequest, user: User,
                        extra_metadata: Optional[Dict[str, Any]] = None) -> Call:
    """Creates the test Call and starts its runtime session, as the carrier webhook does for a phone call."""
    agent = db.get(Agent, req.agent_id)
    version = db.get(AgentVersion, req.agent_version_id)
    if not agent or not version or version.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="AI Employee version not found.")

    # Outbound agents are tested as if they had called the tester
    direction_setting = str(((version.configuration_json or {}).get("business_context") or {}).get("call_direction") or "inbound")
    outbound = direction_setting.lower() == "outbound"
    call_id = generate_unique_id("call", 12)
    caller, destination = ("browser", TEST_CALL_PHONE) if outbound else (TEST_CALL_PHONE, "browser")

    variables = {k: v.strip() for k, v in (("user_name", req.user_name), ("company_name", req.company_name)) if v and v.strip()}
    session_obj = AgentRuntime(db, registry=default_registry).start_session(
        agent_id=agent.id,
        agent_version_id=version.id,
        metadata={
            "origin": "telephony_outbound" if outbound else "telephony_inbound",
            "channel": "browser",
            "is_test": True,
            "call_id": call_id,
            "provider": "browser",
            "caller": caller,
            "destination": destination,
            **variables,
        },
    )
    now = datetime.now(timezone.utc)
    return CallRepository(db).create(Call(
        id=call_id,
        client_id=agent.client_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        runtime_session_id=session_obj.id,
        provider="browser",
        provider_call_id=generate_unique_id("web", 16),
        direction="OUTBOUND" if outbound else "INBOUND",
        caller_number=caller,
        destination_number=destination,
        status="ANSWERED",
        started_at=now,
        answered_at=now,
        duration_seconds=0.0,
        metadata_={"is_test": True, "channel": "browser", "started_by": user.id, "variables": variables,
                   **(extra_metadata or {})},
    ))


# A call nobody connects to (e.g. the browser gave up) is ended after this long
CONNECT_TIMEOUT_S = 30


async def _start_call(db: Session, req: BrowserCallRequest, user: User,
                      extra_metadata: Optional[Dict[str, Any]] = None,
                      on_end: Optional[Callable[[Session, str, Optional[float]], None]] = None) -> BrowserCallResponse:
    """Creates the test call and answers the browser's offer. Readiness errors become 4xx responses."""
    try:
        call_record = _create_call_record(db, req, user, extra_metadata)
    except Exception:
        if on_end:  # no call was made, so it ends here
            if not db.is_active:  # a database error left the session needing a rollback
                db.rollback()
            on_end(db, "not_started", None)
        raise

    call = BrowserCall(call_record.id, on_end=on_end)
    active_browser_calls[call.call_id] = call
    try:
        answer = await call.connect(RTCSessionDescription(sdp=req.sdp, type=req.type))
    except Exception as e:
        logger.error(f"Browser call {call.call_id}: WebRTC negotiation failed: {type(e).__name__}: {e}")
        await call.end("connection_failed")
        raise HTTPException(status_code=400, detail="Could not set up the audio connection.")

    async def expire_if_unconnected():
        await asyncio.sleep(CONNECT_TIMEOUT_S)
        if not call._started:
            await call.end("connection_timeout")
    asyncio.create_task(expire_if_unconnected())

    return BrowserCallResponse(
        call_id=call_record.id,
        runtime_session_id=call_record.runtime_session_id,
        sdp=answer.sdp,
        type=answer.type,
    )


@router.post("", response_model=BrowserCallResponse, status_code=status.HTTP_201_CREATED)
async def start_browser_call(
    req: BrowserCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
):
    """Starts a free test call with an AI Employee from the browser (WebRTC SDP offer in, answer out)."""
    if req.type != "offer":
        raise HTTPException(status_code=400, detail="Expected an SDP offer.")
    return await _start_call(db, req, current_user)


@router.post("/{call_id}/hangup")
async def hang_up_browser_call(call_id: str, _: User = Depends(require_operator)):
    """Ends a browser test call (the tester pressed End Call)."""
    call = active_browser_calls.get(call_id)
    if call:
        await call.end("caller_hangup")
    return {"status": "ended", "call_id": call_id}


# ---------------------------------------------------------------- client trial calls

portal_router = APIRouter(prefix="/portal/agent-requests", tags=["Client Portal"])


class TrialCallRequest(BaseModel):
    sdp: str = Field(..., description="The browser's SDP offer (with ICE candidates gathered)")
    type: str = "offer"


def _trial_call_ended(request_id: str) -> Callable[[Session, str, Optional[float]], None]:
    def on_end(db: Session, reason: str, connected_seconds: Optional[float]) -> None:
        if not agent_requests.trial_call_counts(reason, connected_seconds):
            agent_requests.release_trial_call(db, request_id)
    return on_end


@portal_router.post("/{request_id}/trial-call", response_model=BrowserCallResponse, status_code=status.HTTP_201_CREATED)
async def start_trial_call(
    request_id: str,
    req: TrialCallRequest,
    account: Tuple[User, str] = Depends(require_client_user),
    db: Session = Depends(get_db),
):
    """
    The client tries the AI employee the team sent them: a short, free browser call. The server picks the
    employee and its published version, so a client can only ever reach their own.
    """
    user, client_id = account
    if req.type != "offer":
        raise HTTPException(status_code=400, detail="Expected an SDP offer.")
    if not billing.browser_session_allowed(db):
        raise HTTPException(status_code=429, detail=billing.PLATFORM_BUSY_REASON)
    request, agent, version = agent_requests.reserve_trial_call(db, request_id, client_id)
    call_req = BrowserCallRequest(agent_id=agent.id, agent_version_id=version.id, sdp=req.sdp, type=req.type,
                                  user_name=user.name or None, company_name=request.company_name or None)
    extra = {"trial_request_id": request.id, "max_duration_s": settings.CLIENT_TRIAL_MAX_DURATION_S}
    return await _start_call(db, call_req, user, extra_metadata=extra, on_end=_trial_call_ended(request.id))


@portal_router.post("/{request_id}/trial-call/{call_id}/hangup")
async def hang_up_trial_call(request_id: str, call_id: str, account: Tuple[User, str] = Depends(require_client_user),
                             db: Session = Depends(get_db)):
    """Ends the client's trial call (they pressed End Call)."""
    _, client_id = account
    record = db.get(Call, call_id)
    if not record or record.client_id != client_id or (record.metadata_ or {}).get("trial_request_id") != request_id:
        raise HTTPException(status_code=404, detail="Call not found.")
    call = active_browser_calls.get(call_id)
    if call:
        await call.end("caller_hangup")
    return {"status": "ended", "call_id": call_id}
