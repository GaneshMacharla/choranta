import asyncio
import fractions
import json
import logging
import struct
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set
import av
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.mediastreams import MediaStreamError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import decode_and_verify_token, generate_unique_id
from app.db.session import SessionLocal, get_db
from app.models.runtime_session import RuntimeSession
from app.models.agent_version import AgentVersion
from app.models.runtime_event import RuntimeEvent
from app.schemas.agent_spec import CanonicalAgentSpec
from app.runtime.context import RuntimeContext
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.repositories.user_repository import UserRepository
from app.runtime.events.emitter import EventEmitter, scrub_payload
from app.runtime.events.types import RuntimeEventType, RuntimeEventPayload
from app.runtime.lifecycle import SessionStatus
from app.runtime.runtime import AgentRuntime
from app.runtime.providers.registry import default_registry

logger = logging.getLogger("choranta.runtime.webrtc")

router = APIRouter(tags=["WebRTC Voice Transport"])

# Active WebRTC PeerConnections mapped by session_id
active_webrtc_connections: Dict[str, RTCPeerConnection] = {}


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str


class WebRTCAnswerResponse(BaseModel):
    sdp: str
    type: str


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


def _authenticate_request(token: Optional[str], db: Session) -> Optional[str]:
    """Authenticates WebRTC signaling request via Bearer JWT token."""
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
        logger.warning(f"WebRTC auth failed: {e}")
        return None


def _update_session_usage(session_id: str, usage_summary: dict):
    """Safely updates session usage metrics in DB using dedicated scoped session."""
    try:
        with SessionLocal() as db_session:
            repo = RuntimeSessionRepository(db_session)
            rec = repo.get_by_id(session_id)
            if rec:
                rec.usage_json = usage_summary
                repo.update(rec)
    except Exception as e:
        logger.warning(f"Failed to update session usage for {session_id}: {e}")


class WebRTCEmitter(EventEmitter):
    """
    Independent event emitter for long-lived WebRTC connections.
    Uses its own scoped database sessions to persist runtime events safely
    without relying on the short-lived HTTP request db session.
    """
    def __init__(self):
        super().__init__(db=None)

    def emit(
        self,
        event_type: RuntimeEventType,
        session_id: str,
        agent_id: str,
        agent_version_id: str,
        client_id: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> RuntimeEventPayload:
        event_id = generate_unique_id("evt", 12)
        safe_payload = scrub_payload(payload or {})
        event_obj = RuntimeEventPayload(
            event_id=event_id,
            session_id=session_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            client_id=client_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=safe_payload
        )

        for listener in self._listeners:
            try:
                listener(event_obj)
            except Exception as e:
                logger.error(f"Error in WebRTC event listener for {event_type}: {e}")

        try:
            with SessionLocal() as db_session:
                RuntimeEventRepository(db_session).create(
                    RuntimeEvent(
                        id=event_id,
                        session_id=session_id,
                        client_id=client_id,
                        agent_id=agent_id,
                        agent_version_id=agent_version_id,
                        event_type=event_type.value,
                        payload_json=safe_payload,
                        timestamp=event_obj.timestamp
                    )
                )
        except Exception as e:
            logger.debug(f"Failed to persist WebRTC event {event_id}: {e}")

        logger.info(f"[RUNTIME EVENT] {event_type.value} | session={session_id} | agent={agent_id}")
        return event_obj


class AgentAudioOutputTrack(MediaStreamTrack):
    """
    Paced WebRTC outgoing audio track streaming synthesized agent voice
    as 16kHz s16 mono frames (which aiortc encodes into Opus RTP packets).
    Uses clock-based pacing (20ms cadence) to prevent packet bursts.
    """
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer: bytearray = bytearray()
        self._pts: int = 0
        self._silence_frame = b"\x00\x00" * 320  # 20ms of silence at 16kHz (640 bytes)
        self._sample_rate = 16000
        self._samples = 320
        self._start_time: Optional[float] = None

    def enqueue_chunk(self, chunk: bytes):
        self._queue.put_nowait(chunk)

    def clear(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._buffer.clear()

    async def recv(self) -> av.AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError

        now = time.time()
        if self._start_time is None:
            self._start_time = now
            self._pts = 0
        else:
            self._pts += self._samples
            expected_time = self._start_time + (self._pts / self._sample_rate)
            wait = expected_time - now
            if wait > 0:
                await asyncio.sleep(wait)

        # Pull incoming chunks into buffer
        while len(self._buffer) < 640 and not self._queue.empty():
            try:
                chunk = self._queue.get_nowait()
                self._buffer.extend(chunk)
            except asyncio.QueueEmpty:
                break

        if len(self._buffer) >= 640:
            frame_bytes = bytes(self._buffer[:640])
            del self._buffer[:640]
        else:
            frame_bytes = self._silence_frame

        frame = av.AudioFrame(format="s16", layout="mono", samples=self._samples)
        frame.planes[0].update(frame_bytes)
        frame.sample_rate = self._sample_rate
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        frame.pts = self._pts
        return frame


@router.post("/api/runtime/sessions/{session_id}/webrtc/offer", response_model=WebRTCAnswerResponse)
@router.post("/api/v1/runtime/sessions/{session_id}/webrtc/offer", response_model=WebRTCAnswerResponse)
async def handle_webrtc_offer(
    session_id: str,
    offer_req: WebRTCOfferRequest,
    token: Optional[str] = Query(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    WebRTC SDP Offer / Answer Exchange Endpoint.
    Initiates a peer-to-peer WebRTC connection using Opus audio and an events DataChannel.
    """
    # 1. Auth verification (header or query token)
    auth_header = request.headers.get("Authorization", "") if request else ""
    raw_token = token
    if not raw_token and auth_header.startswith("Bearer "):
        raw_token = auth_header.replace("Bearer ", "").strip()

    user_id = _authenticate_request(raw_token, db)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # 2. Verify Session
    session_repo = RuntimeSessionRepository(db)
    session_record = session_repo.get_by_id(session_id)
    if not session_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session_record.status not in (SessionStatus.ACTIVE.value, SessionStatus.CREATED.value, SessionStatus.INITIALIZING.value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is {session_record.status}")

    # Close any existing WebRTC connection for this session
    if session_id in active_webrtc_connections:
        try:
            await active_webrtc_connections[session_id].close()
        except Exception:
            pass
        active_webrtc_connections.pop(session_id, None)

    # 3. Initialize Runtime Context & Providers
    runtime = AgentRuntime(db, registry=default_registry)
    emitter = WebRTCEmitter()

    context = runtime._contexts.get(session_id)
    if not context:
        version = db.query(AgentVersion).filter(AgentVersion.id == session_record.agent_version_id).first()
        spec = CanonicalAgentSpec.model_validate(version.configuration_json)
        context = RuntimeContext(
            session_id=session_id,
            agent_id=session_record.agent_id,
            client_id=session_record.client_id,
            agent_version_id=session_record.agent_version_id,
            agent_spec=spec,
            metadata=session_record.metadata_
        )
        runtime._contexts[session_id] = context

    stt_provider = default_registry.get_stt(context.agent_spec.providers.stt)
    llm_provider = default_registry.get_llm(context.agent_spec.providers.llm)
    tts_provider = default_registry.get_tts(context.agent_spec.providers.tts)

    # 4. State & Tracks
    agent_output_track = AgentAudioOutputTrack()
    data_channel_ref: Dict[str, Any] = {"channel": None}
    streaming_stt_session: Optional[Any] = None
    assistant_speaking = False
    assistant_audio_grace_until = 0.0
    current_tts_task: Optional[asyncio.Task] = None
    turn_in_progress = False

    # Latency tracking
    t_speech_start: Optional[float] = None
    t_stt_partial: Optional[float] = None
    t_speech_end: Optional[float] = None

    def send_dc_event(event_dict: dict):
        dc = data_channel_ref.get("channel")
        if dc and dc.readyState == "open":
            try:
                dc.send(json.dumps(event_dict))
            except Exception as e:
                logger.debug(f"DataChannel send failed: {e}")

    async def on_stt_partial(partial_text: str):
        nonlocal t_stt_partial, t_speech_start
        if not partial_text:
            return
        if t_stt_partial is None and t_speech_start is not None:
            t_stt_partial = time.perf_counter()

        emitter.emit(
            RuntimeEventType.USER_TRANSCRIPT_PARTIAL,
            session_id=session_id,
            agent_id=context.agent_id,
            agent_version_id=context.agent_version_id,
            client_id=context.client_id,
            payload={"text": partial_text}
        )
        send_dc_event({
            "type": "transcript",
            "text": partial_text,
            "final": False
        })

    async def ensure_streaming_stt() -> Any:
        nonlocal streaming_stt_session
        if not settings.CARTESIA_ENABLE_STREAMING_STT:
            return None
        if streaming_stt_session is None:
            try:
                streaming_stt_session = await stt_provider.create_stream(
                    on_partial=on_stt_partial
                )
            except Exception as e:
                logger.warning(f"Failed to create streaming STT session: {e}")
                streaming_stt_session = None
        return streaming_stt_session

    async def send_tts_stream(text: str, t_ref_speech_end: Optional[float] = None, stt_ms: float = 0.0, llm_ms: float = 0.0):
        nonlocal assistant_speaking, assistant_audio_grace_until
        assistant_speaking = True
        t_tts_start = time.perf_counter()
        t_tts_first_chunk: Optional[float] = None

        try:
            emitter.emit(
                RuntimeEventType.TTS_STARTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"text": text, "voice_id": context.agent_spec.voice.voice_id}
            )

            total_bytes = 0
            async for audio_chunk in tts_provider.synthesize_stream(
                text=text,
                voice_id=context.agent_spec.voice.voice_id,
                speed=context.agent_spec.voice.speed
            ):
                if not assistant_speaking:
                    logger.info(f"WebRTC TTS stream aborted for session '{session_id}' due to barge-in.")
                    break

                if audio_chunk:
                    if t_tts_first_chunk is None:
                        t_tts_first_chunk = time.perf_counter()
                        ttfb_ms = round((t_tts_first_chunk - t_tts_start) * 1000, 2)
                        round_trip_ms = round((t_tts_first_chunk - t_ref_speech_end) * 1000, 2) if t_ref_speech_end else None

                        send_dc_event({
                            "type": "latency_metrics",
                            "metrics": {
                                "stt_ms": stt_ms,
                                "llm_ms": llm_ms,
                                "tts_ttfb_ms": ttfb_ms,
                                "round_trip_ms": round_trip_ms
                            }
                        })

                    total_bytes += len(audio_chunk)
                    agent_output_track.enqueue_chunk(audio_chunk)
                    emitter.emit(
                        RuntimeEventType.TTS_AUDIO_CHUNK,
                        session_id=session_id,
                        agent_id=context.agent_id,
                        agent_version_id=context.agent_version_id,
                        client_id=context.client_id,
                        payload={"chunk_bytes": len(audio_chunk)}
                    )
                    await asyncio.sleep(0.001)

            duration = total_bytes / (16000 * 2)
            context.usage_tracker.record_tts(duration)
            emitter.emit(
                RuntimeEventType.TTS_COMPLETED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"duration_seconds": duration, "interrupted": not assistant_speaking}
            )

            if assistant_speaking:
                send_dc_event({
                    "type": "turn_complete",
                    "usage": context.usage_tracker.get_summary()
                })
        except asyncio.CancelledError:
            logger.info(f"WebRTC TTS cancelled via barge-in for session '{session_id}'")
            agent_output_track.clear()
            send_dc_event({"type": "interrupted"})
        except Exception as e:
            logger.error(f"WebRTC TTS error: {e}")
            send_dc_event({"type": "error", "message": str(e)})
        finally:
            assistant_speaking = False
            assistant_audio_grace_until = time.perf_counter() + 0.75

    async def handle_interrupt(reason: str = "barge_in"):
        nonlocal assistant_speaking, assistant_audio_grace_until, current_tts_task
        assistant_speaking = False
        assistant_audio_grace_until = time.perf_counter() + 0.75
        agent_output_track.clear()
        if current_tts_task and not current_tts_task.done():
            current_tts_task.cancel()
        emitter.emit(
            RuntimeEventType.ASSISTANT_INTERRUPTED,
            session_id=session_id,
            agent_id=context.agent_id,
            agent_version_id=context.agent_version_id,
            client_id=context.client_id,
            payload={"reason": reason}
        )
        send_dc_event({"type": "interrupted"})

    async def execute_turn(user_audio_bytes: bytes, t_ref_speech_start: Optional[float] = None, t_ref_speech_end: Optional[float] = None):
        nonlocal turn_in_progress, current_tts_task, streaming_stt_session
        if turn_in_progress:
            return
        turn_in_progress = True
        t_end = t_ref_speech_end or time.perf_counter()

        try:
            emitter.emit(
                RuntimeEventType.USER_SPEECH_STARTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id
            )

            if streaming_stt_session:
                transcript_res = await streaming_stt_session.finish()
                streaming_stt_session = None
            else:
                transcript_res = await stt_provider.process_audio_async(user_audio_bytes)

            # Streaming STT can finish without a final transcript when the provider
            # misses the last event. Retry the captured turn through batch STT.
            if not transcript_res.text.strip() and user_audio_bytes:
                transcript_res = await stt_provider.process_audio_async(user_audio_bytes)

            t_stt_done = time.perf_counter()
            stt_latency_ms = round((t_stt_done - t_end) * 1000, 2)
            user_text = transcript_res.text.strip()
            context.usage_tracker.record_stt(len(user_audio_bytes) / (16000 * 2))

            emitter.emit(
                RuntimeEventType.USER_TRANSCRIPT_FINAL,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"text": user_text, "confidence": transcript_res.confidence, "latency_ms": stt_latency_ms}
            )

            if not user_text:
                return

            send_dc_event({
                "type": "transcript",
                "text": user_text,
                "final": True
            })

            context.conversation.add_user_message(user_text)

            # LLM Invocation
            t_llm_start = time.perf_counter()
            emitter.emit(
                RuntimeEventType.LLM_REQUEST_STARTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id
            )

            available_tools_list = [{"name": t, "id": t} for t in context.active_tools]
            llm_result = await llm_provider.generate_async(
                system_instruction=context.conversation.system_instruction,
                messages=context.conversation.to_llm_messages(),
                available_tools=available_tools_list
            )

            t_llm_done = time.perf_counter()
            llm_latency_ms = round((t_llm_done - t_llm_start) * 1000, 2)

            context.usage_tracker.record_llm(
                llm_result.usage.get("input_tokens", 0),
                llm_result.usage.get("output_tokens", 0)
            )

            emitter.emit(
                RuntimeEventType.LLM_RESPONSE,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"latency_ms": llm_latency_ms, "finish_reason": llm_result.finish_reason}
            )

            assistant_text = llm_result.text or context.agent_spec.conversation.fallback_response
            context.conversation.add_assistant_message(content=assistant_text)

            emitter.emit(
                RuntimeEventType.ASSISTANT_RESPONSE,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"text": assistant_text}
            )

            send_dc_event({
                "type": "assistant_text",
                "text": assistant_text
            })

            # Update session usage in DB safely
            _update_session_usage(session_id, context.usage_tracker.get_summary())

            # Stream TTS Audio over WebRTC
            current_tts_task = asyncio.create_task(
                send_tts_stream(
                    assistant_text,
                    t_ref_speech_end=t_end,
                    stt_ms=stt_latency_ms,
                    llm_ms=llm_latency_ms
                )
            )
            await current_tts_task

        except Exception as e:
            logger.error(f"WebRTC turn execution error: {e}")
            send_dc_event({"type": "error", "message": str(e)})
        finally:
            turn_in_progress = False

    # 5. Build RTCPeerConnection
    pc = RTCPeerConnection(
        configuration=RTCConfiguration(
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        )
    )
    active_webrtc_connections[session_id] = pc

    # Add agent audio track to peer connection
    pc.addTrack(agent_output_track)

    @pc.on("datachannel")
    def on_datachannel(channel):
        data_channel_ref["channel"] = channel
        logger.info(f"WebRTC DataChannel '{channel.label}' established for session '{session_id}'")

        @channel.on("message")
        def on_message(msg_str):
            try:
                msg = json.loads(msg_str)
                mtype = msg.get("type")
                if mtype == "interrupt":
                    asyncio.create_task(handle_interrupt("user_interrupt"))
                elif mtype == "ping":
                    send_dc_event({"type": "pong"})
            except Exception as err:
                logger.debug(f"DataChannel message parse error: {err}")

        def trigger_greeting():
            has_dialogue = any(m.role.value in ("user", "assistant") for m in context.conversation.messages)
            if context.agent_spec.conversation.greeting and not has_dialogue:
                greeting_text = context.resolved_greeting or context.agent_spec.conversation.greeting
                context.conversation.add_assistant_message(content=greeting_text)
                send_dc_event({"type": "assistant_text", "text": greeting_text})
                asyncio.create_task(send_tts_stream(greeting_text))

        @channel.on("open")
        def on_open():
            logger.info(f"DataChannel open for session '{session_id}'")
            trigger_greeting()

        if channel.readyState == "open":
            trigger_greeting()

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            logger.info(f"Received caller audio track on WebRTC session '{session_id}'")
            asyncio.create_task(consume_caller_audio(track))

    async def consume_caller_audio(incoming_track: MediaStreamTrack):
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        audio_buffer = bytearray()
        speech_energy_count = 0
        has_spoken = False
        last_speech_time = 0.0

        try:
            while True:
                frame = await incoming_track.recv()
                resampled_frames = resampler.resample(frame)

                for r_frame in resampled_frames:
                    raw_pcm = r_frame.to_ndarray().tobytes()

                    # Ignore speaker echo while the assistant is talking and for
                    # a short decay window after playback stops.
                    if assistant_speaking or time.perf_counter() < assistant_audio_grace_until:
                        speech_energy_count = 0
                        has_spoken = False
                        audio_buffer.clear()
                        continue

                    has_energy = _is_voice_energy(raw_pcm, threshold=1200)

                    if has_energy:
                        speech_energy_count += 1
                        if speech_energy_count >= 3:
                            has_spoken = True
                            last_speech_time = time.perf_counter()

                    else:
                        speech_energy_count = max(0, speech_energy_count - 1)

                    if has_spoken and not assistant_speaking:
                        stt_stream = await ensure_streaming_stt()
                        if stt_stream:
                            await stt_stream.send_audio(raw_pcm)
                        audio_buffer.extend(raw_pcm)

                    # Silence pause VAD: auto-execute after one second of silence.
                    if has_spoken and (time.perf_counter() - last_speech_time > 1.0) and not turn_in_progress:
                        if len(audio_buffer) > 0:
                            turn_bytes = bytes(audio_buffer)
                            audio_buffer.clear()
                            has_spoken = False
                            asyncio.create_task(
                                execute_turn(
                                    turn_bytes,
                                    t_ref_speech_start=last_speech_time - 1.0,
                                    t_ref_speech_end=last_speech_time
                                )
                            )
        except Exception as e:
            logger.debug(f"WebRTC incoming audio stream ended: {e}")

    # Set Remote Offer and Create Local Answer
    offer = RTCSessionDescription(sdp=offer_req.sdp, type=offer_req.type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return WebRTCAnswerResponse(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type
    )


@router.post("/api/runtime/sessions/{session_id}/webrtc/close")
@router.post("/api/v1/runtime/sessions/{session_id}/webrtc/close")
async def close_webrtc_session(session_id: str):
    """Closes an active WebRTC peer connection."""
    pc = active_webrtc_connections.pop(session_id, None)
    if pc:
        try:
            await pc.close()
        except Exception:
            pass
    return {"status": "closed", "session_id": session_id}
