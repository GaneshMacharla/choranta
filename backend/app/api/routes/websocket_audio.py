"""
Real-time voice conversation over a WebSocket: talk to an AI Employee with raw 16kHz PCM audio.

The conversation runs through the same TelephonyMediaSession as a phone call (server-side endpointing,
LLM replies streamed sentence by sentence into speech, fillers, barge-in that keeps only what the
caller heard, call limits, recording, quality stats), with the WebSocket as the carrier. What you hear
when testing here is what a caller hears on the phone.

Protocol (client -> server)
  binary            16-bit mono PCM at 16kHz, any frame size (~20-100 ms is typical). Send continuously:
                    the server decides when the caller has finished speaking.
  {"type":"text_input","text":...}   a typed caller turn
  {"type":"interrupt"}               stop the agent now
  {"type":"stop"}                    the caller finished speaking (optional, for push-to-talk clients)
  {"type":"ping"}                    keepalive -> {"type":"pong"}

Protocol (server -> client)
  binary            agent audio, 16-bit mono PCM at 16kHz, paced to real time; play it in order
  transcript        {"text", "final": true} the caller's words
  assistant_text_delta  {"text"} a sentence of the reply as it starts playing
  assistant_text    {"text", "interrupted"} the reply as the caller heard it, once the turn ends
  latency_metrics   {"metrics": {stt_ms, llm_ms, tts_ttfb_ms, round_trip_ms}} at the reply's first audio
  interrupted       the agent stopped talking: drop any audio not yet played
  turn_complete     {"usage"} the agent finished its turn
  tool_started      {"tool_name"}
  call_ended        {"reason"} the agent hung up (silence, goodbye, maximum length)
  error             {"message"}
"""
import asyncio
import json
import logging
import struct
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

import anyio

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_and_verify_token, generate_unique_id
from app.db.session import get_db
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.repositories.call_repository import CallRepository
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.repositories.user_repository import UserRepository
from app.runtime.context import TEST_CALL_PHONE
from app.runtime.events.types import RuntimeEventType
from app.runtime.lifecycle import SessionStatus
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony.browser import BrowserTelephonyProvider
from app.runtime.runtime import AgentRuntime
from app.runtime.telephony.session import TelephonyMediaSession

logger = logging.getLogger("choranta.runtime.websocket")

router = APIRouter(tags=["Realtime Audio Transport"])

# Runtime sessions with an audio WebSocket open (one connection per session)
active_audio_sessions: Set[str] = set()


def _is_voice_energy(pcm_bytes: bytes, threshold: int = 1200) -> bool:
    """Computes RMS amplitude of 16-bit signed PCM frame to detect speech energy."""
    count = len(pcm_bytes) // 2
    if count == 0:
        return False
    try:
        shorts = struct.unpack(f"<{count}h", pcm_bytes[:count * 2])
        rms = (sum(s * s for s in shorts) / count) ** 0.5
        return rms > threshold
    except Exception:
        return False


def _authenticate_ws(token: Optional[str], db: Session) -> Optional[str]:
    """Authenticates WebSocket handshake via Bearer JWT query parameter."""
    if not token:
        return None
    try:
        payload = decode_and_verify_token(token.strip())
        user_id = payload.get("sub")
        if not user_id:
            return None
        user_repo = UserRepository(db)
        user = user_repo.get_by_id(user_id) or user_repo.get_by_email(payload.get("email", ""))
        if not user or user.status != "ACTIVE" or user.role not in ("ADMIN", "OPERATOR"):
            return None
        return user.id
    except Exception as e:
        logger.warning(f"WebSocket auth failed: {e}")
        return None


class WebSocketMediaSession(TelephonyMediaSession):
    """A phone call session whose carrier is a raw-PCM WebSocket (16kHz both ways)."""

    # The workbench ends the runtime session itself; reconnecting continues the same conversation
    end_runtime_session_on_close = False

    def __init__(self, websocket: WebSocket, call_record: Call, db: Session):
        super().__init__(
            websocket=websocket,
            call_record=call_record,
            stream_sid=call_record.provider_call_id,
            db=db,
            telephony_provider=BrowserTelephonyProvider(),
        )
        # Everything to the client (audio and messages) goes through one queue, so it arrives in order
        self._outbox: "asyncio.Queue[Optional[Any]]" = asyncio.Queue()
        self._writer: Optional[asyncio.Task] = None
        self._socket_open = True

    def start_writer(self) -> None:
        self._writer = asyncio.create_task(self._write_loop())

    async def stop_writer(self) -> None:
        if self._writer and not self._writer.done():
            self._outbox.put_nowait(None)
            try:
                await asyncio.wait_for(self._writer, timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                self._writer.cancel()
        self._socket_open = False

    async def _write_loop(self) -> None:
        while True:
            item = await self._outbox.get()
            if item is None or not self._socket_open:
                return
            try:
                if isinstance(item, bytes):
                    await self.websocket.send_bytes(item)
                else:
                    await self.websocket.send_text(item)
            except Exception:
                self._socket_open = False
                return

    def _notify(self, message: Dict[str, Any]) -> None:
        if self._socket_open:
            self._outbox.put_nowait(json.dumps(message, default=str))

    async def send_json(self, message: Dict[str, Any]) -> None:
        self._notify(message)

    def _should_greet(self) -> bool:
        # Reconnecting mid-conversation continues it rather than greeting again
        return not any(m.role.value in ("user", "assistant") for m in self.context.conversation.messages)

    # Carrier transport

    async def _send_carrier_audio(self, frame: bytes) -> None:
        if self._socket_open:
            self._outbox.put_nowait(bytes(frame))

    async def _clear_carrier_playback(self) -> None:
        await self.send_json({"type": "interrupted"})

    async def _disconnect_carrier(self) -> None:
        await self.send_json({"type": "call_ended", "reason": self._end_reason or "agent_ended"})
        await self.stop_writer()
        try:
            await self.websocket.close()
        except Exception:
            pass

    # Live conversation events

    def _on_sentence_playing(self, turn, sentence) -> None:
        self._notify({"type": "assistant_text_delta", "text": sentence.text, "filler": bool(sentence.filler_kind)})

    def _on_sentence_text(self, turn, sentence, text) -> None:
        self._notify({"type": "assistant_text_delta", "text": text, "filler": False})

    def _emit(self, event_type: RuntimeEventType, payload: Dict[str, Any]) -> None:
        super()._emit(event_type, payload)
        if event_type == RuntimeEventType.USER_TRANSCRIPT_FINAL:
            self._notify({"type": "transcript", "text": payload.get("text", ""), "final": True})
        elif event_type == RuntimeEventType.ASSISTANT_RESPONSE:
            self._notify({"type": "assistant_text", "text": payload.get("text", ""),
                          "interrupted": bool(payload.get("interrupted"))})
        elif event_type == RuntimeEventType.TTS_STARTED and "response_latency_ms" in payload:
            round_trip = payload.get("response_latency_ms")
            stt_ms = payload.get("stt_ms") or 0
            llm_ms = payload.get("llm_first_token_ms") or 0
            self._notify({"type": "latency_metrics", "metrics": {
                "stt_ms": stt_ms,
                "llm_ms": llm_ms,
                "tts_ttfb_ms": max(0, (round_trip or 0) - stt_ms - llm_ms),
                "round_trip_ms": round_trip,
                "first_audio_filler": payload.get("first_audio_filler"),
            }})
        elif event_type == RuntimeEventType.TOOL_CALL_STARTED:
            self._notify({"type": "tool_started", "tool_name": payload.get("tool_name")})

    async def _run_turn(self, turn, coro) -> None:
        await super()._run_turn(turn, coro)
        if self.context and not self._end_call_requested:
            await self.send_json({"type": "turn_complete", "usage": self.context.usage_tracker.get_summary()})

    # Client control messages

    async def end_caller_turn(self) -> None:
        """Push-to-talk release: whatever the caller said so far is their complete turn."""
        event = self.endpointer.flush()
        if event is not None and event.audio:
            self._cancel_early_transcript()
            await self.execute_turn(event.audio)

    async def interrupt(self) -> None:
        """The client asked the agent to stop talking: end the reply, keeping only what was heard."""
        if self._turn_task and not self._turn_task.done():
            self._pause_time = self._pause_time or time.monotonic()
            self._barge_ins += 1
        await self._interrupt_current_turn()
        self._emit(RuntimeEventType.ASSISTANT_INTERRUPTED, {"reason": "user_interrupt"})
        await self.send_json({"type": "interrupted"})


def _create_call_record(db: Session, session_record, user_id: str) -> Call:
    """A test Call for this connection, so it gets a recording, quality stats and a call-log entry (never billed)."""
    version = db.get(AgentVersion, session_record.agent_version_id)
    business = ((version.configuration_json or {}).get("business_context") or {}) if version else {}
    outbound = str(business.get("call_direction") or "inbound").lower() == "outbound"
    caller, destination = ("websocket", TEST_CALL_PHONE) if outbound else (TEST_CALL_PHONE, "websocket")
    now = datetime.now(timezone.utc)
    return CallRepository(db).create(Call(
        id=generate_unique_id("call", 12),
        client_id=session_record.client_id,
        agent_id=session_record.agent_id,
        agent_version_id=session_record.agent_version_id,
        runtime_session_id=session_record.id,
        provider="browser",
        provider_call_id=generate_unique_id("wss", 16),
        direction="OUTBOUND" if outbound else "INBOUND",
        caller_number=caller,
        destination_number=destination,
        status="ANSWERED",
        started_at=now,
        answered_at=now,
        duration_seconds=0.0,
        metadata_={"is_test": True, "channel": "websocket", "started_by": user_id},
    ))


@router.websocket("/ws/runtime/sessions/{session_id}/audio")
@router.websocket("/api/v1/runtime/sessions/{session_id}/audio")
async def runtime_audio_websocket(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Real-time voice conversation with a runtime session over raw 16kHz PCM (see the module docstring)."""
    user_id = _authenticate_ws(token, db)
    if not user_id:
        logger.warning(f"Rejecting unauthorized WebSocket connection for session '{session_id}'")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    if len(active_audio_sessions) >= settings.MAX_CONCURRENT_SESSIONS:
        logger.warning(f"Max concurrent sessions limit ({settings.MAX_CONCURRENT_SESSIONS}) reached.")
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="Server capacity reached")
        return

    session_record = RuntimeSessionRepository(db).get_by_id(session_id)
    if not session_record:
        logger.warning(f"RuntimeSession '{session_id}' does not exist.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session not found")
        return
    if session_record.status != SessionStatus.ACTIVE.value:
        logger.warning(f"RuntimeSession '{session_id}' is in inactive state '{session_record.status}'.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session not active")
        return
    if session_id in active_audio_sessions:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session already has an audio connection")
        return

    await websocket.accept()
    active_audio_sessions.add(session_id)

    session: Optional[WebSocketMediaSession] = None
    try:
        call_record = _create_call_record(db, session_record, user_id)
        session = WebSocketMediaSession(websocket, call_record, db)
        session.runtime = AgentRuntime(db, registry=default_registry)
        session.start_writer()
        await session.initialize()  # plays the greeting
        session._emit(RuntimeEventType.AUDIO_SESSION_CONNECTED, {
            "transport": "websocket", "sample_rate": 16000, "channels": 1, "format": "pcm_s16le",
            "call_id": call_record.id,
        })

        while not session.closed:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            raw = message.get("bytes")
            if raw:
                if len(raw) > settings.MAX_AUDIO_FRAME_SIZE:
                    logger.warning(f"Audio frame exceeds max size limit ({len(raw)} bytes)")
                    continue
                await session.handle_carrier_audio(raw)
                continue

            text = message.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Received invalid JSON payload over audio WebSocket")
                continue
            kind = payload.get("type", "")
            if kind == "ping":
                await session.send_json({"type": "pong"})
            elif kind == "interrupt":
                await session.interrupt()
            elif kind == "stop":
                await session.end_caller_turn()
            elif kind == "text_input":
                await session.handle_text_input(payload.get("text", ""))
            # "start" is accepted for older clients: turns are detected on the server

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for session '{session_id}'")
    except Exception as e:
        logger.error(f"WebSocket session error: {type(e).__name__}: {e}")
        if session:
            await session.send_json({"type": "error", "message": str(e)})
    finally:
        # Shielded: closing saves the recording, flushes events and settles usage even if the task is cancelled
        with anyio.CancelScope(shield=True):
            await _finish(session, session_record, db)
        active_audio_sessions.discard(session_id)


async def _finish(session: Optional[WebSocketMediaSession], session_record, db: Session) -> None:
    if not session:
        return
    session._socket_open = False
    if session._writer and not session._writer.done():
        session._writer.cancel()
    session._emit(RuntimeEventType.AUDIO_SESSION_DISCONNECTED, {"call_id": session.call_record.id})
    try:
        await session.close(reason="caller_hangup")
    except Exception as e:
        logger.error(f"Error closing WebSocket call for session '{session_record.id}': {type(e).__name__}: {e}")
    # Keep the session's usage current; the transcript is saved when the session ends
    try:
        if session.context:
            session_record.usage_json = session.context.usage_tracker.get_summary()
            RuntimeSessionRepository(db).update(session_record)
    except Exception:
        pass
