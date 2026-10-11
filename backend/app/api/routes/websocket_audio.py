import asyncio
import json
import logging
from app.runtime.tools.catalog import describe_tools
import struct
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import decode_and_verify_token
from app.db.session import get_db
from app.models.runtime_session import RuntimeSession
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.repositories.user_repository import UserRepository
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.runtime.lifecycle import SessionStatus
from app.runtime.runtime import AgentRuntime
from app.runtime.providers.registry import default_registry

logger = logging.getLogger("choranta.runtime.websocket")

router = APIRouter(tags=["Realtime Audio Transport"])

# Global tracker for concurrent active audio WebSocket connections
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


@router.websocket("/ws/runtime/sessions/{session_id}/audio")
@router.websocket("/api/v1/runtime/sessions/{session_id}/audio")
async def runtime_audio_websocket(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Authenticated Realtime Audio WebSocket Transport.
    Streams 16kHz 16-bit mono PCM audio bidirectional between browser and Choranta Voice Runtime.
    Handles user speech streaming, partial transcripts, barge-in / interruption,
    LLM tool execution, streaming TTS playback, and monotonic latency tracking.
    """
    t_conn_start = time.perf_counter()
    session_record: Optional[RuntimeSession] = None
    assistant_speaking = False
    current_tts_task: Optional[asyncio.Task] = None
    streaming_stt_session: Optional[Any] = None
    turn_in_progress = False

    # Monotonic Turn Latency Tracking
    t_speech_start: Optional[float] = None
    t_stt_partial: Optional[float] = None
    t_speech_end: Optional[float] = None

    # 1. Handshake & Authentication
    user_id = _authenticate_ws(token, db)
    if not user_id:
        logger.warning(f"Rejecting unauthorized WebSocket connection for session '{session_id}'")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    # Check concurrent connection bounds
    if len(active_audio_sessions) >= settings.MAX_CONCURRENT_SESSIONS:
        logger.warning(f"Max concurrent sessions limit ({settings.MAX_CONCURRENT_SESSIONS}) reached.")
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason="Server capacity reached")
        return

    # Verify session existence and active state
    session_repo = RuntimeSessionRepository(db)
    session_record = session_repo.get_by_id(session_id)
    if not session_record:
        logger.warning(f"RuntimeSession '{session_id}' does not exist.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session not found")
        return

    if session_record.status not in (SessionStatus.ACTIVE.value, SessionStatus.CREATED.value, SessionStatus.INITIALIZING.value):
        logger.warning(f"RuntimeSession '{session_id}' is in inactive state '{session_record.status}'.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session not active")
        return

    # Accept WebSocket connection
    await websocket.accept()
    active_audio_sessions.add(session_id)

    runtime = AgentRuntime(db, registry=default_registry)
    emitter = EventEmitter(db)

    t_conn_ready = time.perf_counter()
    conn_latency_ms = round((t_conn_ready - t_conn_start) * 1000, 2)

    emitter.emit(
        RuntimeEventType.AUDIO_SESSION_CONNECTED,
        session_id=session_id,
        agent_id=session_record.agent_id,
        agent_version_id=session_record.agent_version_id,
        client_id=session_record.client_id,
        payload={
            "transport": "websocket",
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "connect_latency_ms": conn_latency_ms
        }
    )

    # Rehydrate or get context
    context = runtime._contexts.get(session_id)
    if not context:
        from app.models.agent_version import AgentVersion
        from app.schemas.agent_spec import CanonicalAgentSpec
        from app.runtime.context import RuntimeContext

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

    audio_buffer = bytearray()
    speech_energy_count = 0
    has_spoken = False

    async def on_stt_partial(partial_text: str):
        """Callback from streaming STT when partial transcript is recognized."""
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
        await websocket.send_json({
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
        nonlocal assistant_speaking
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
                    logger.info(f"TTS stream aborted for session '{session_id}' due to barge-in.")
                    break

                if audio_chunk:
                    if t_tts_first_chunk is None:
                        t_tts_first_chunk = time.perf_counter()
                        ttfb_ms = round((t_tts_first_chunk - t_tts_start) * 1000, 2)
                        round_trip_ms = round((t_tts_first_chunk - t_ref_speech_end) * 1000, 2) if t_ref_speech_end else None

                        # Emit first audio chunk milestone
                        latency_payload = {
                            "stt_ms": stt_ms,
                            "llm_ms": llm_ms,
                            "tts_ttfb_ms": ttfb_ms,
                            "round_trip_ms": round_trip_ms
                        }
                        await websocket.send_json({
                            "type": "latency_metrics",
                            "metrics": latency_payload
                        })

                    total_bytes += len(audio_chunk)
                    await websocket.send_bytes(audio_chunk)
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
                await websocket.send_json({
                    "type": "turn_complete",
                    "usage": context.usage_tracker.get_summary()
                })
        except asyncio.CancelledError:
            logger.info(f"TTS task cancelled via barge-in for session '{session_id}'")
            emitter.emit(
                RuntimeEventType.ASSISTANT_INTERRUPTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"reason": "barge_in"}
            )
            await websocket.send_json({"type": "interrupted"})
        except Exception as e:
            logger.error(f"Error streaming TTS: {e}")
            await websocket.send_json({"type": "error", "message": f"TTS playback error: {str(e)}"})
        finally:
            assistant_speaking = False

    async def handle_interrupt(reason: str = "barge_in"):
        nonlocal assistant_speaking, current_tts_task
        was_speaking = assistant_speaking or (current_tts_task and not current_tts_task.done())
        assistant_speaking = False
        if current_tts_task and not current_tts_task.done():
            current_tts_task.cancel()
        emitter.emit(
            RuntimeEventType.ASSISTANT_INTERRUPTED,
            session_id=session_id,
            agent_id=context.agent_id,
            agent_version_id=context.agent_version_id,
            client_id=context.client_id,
            payload={"reason": reason, "was_speaking": was_speaking}
        )
        await websocket.send_json({"type": "interrupted"})

    async def execute_turn(user_audio_bytes: bytes, t_ref_speech_start: Optional[float] = None, t_ref_speech_end: Optional[float] = None):
        nonlocal turn_in_progress, current_tts_task, streaming_stt_session
        if turn_in_progress:
            return
        turn_in_progress = True

        t_end = t_ref_speech_end or time.perf_counter()

        try:
            # 1. STT Finalization
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
                payload={
                    "text": user_text,
                    "confidence": transcript_res.confidence,
                    "latency_ms": stt_latency_ms
                }
            )

            await websocket.send_json({
                "type": "transcript",
                "text": user_text,
                "final": True
            })

            if not user_text:
                return

            context.conversation.add_user_message(user_text)

            # 2. LLM Invocation & Tool Execution
            t_llm_start = time.perf_counter()
            emitter.emit(
                RuntimeEventType.LLM_REQUEST_STARTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id
            )

            available_tools_list = describe_tools(db, context.active_tools)
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

            # Tool Execution Loop
            if llm_result.tool_calls:
                context.conversation.add_assistant_message(
                    content=llm_result.text,
                    tool_calls=[tc.model_dump() for tc in llm_result.tool_calls]
                )

                for tc in llm_result.tool_calls:
                    emitter.emit(
                        RuntimeEventType.TOOL_CALL_STARTED,
                        session_id=session_id,
                        agent_id=context.agent_id,
                        agent_version_id=context.agent_version_id,
                        client_id=context.client_id,
                        payload={"call_id": tc.id, "tool_name": tc.tool_name, "arguments": tc.arguments}
                    )

                    tool_res = runtime.tool_executor.execute_tool(
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        enabled_tool_ids=context.active_tools
                    )

                    emitter.emit(
                        RuntimeEventType.TOOL_CALL_COMPLETED,
                        session_id=session_id,
                        agent_id=context.agent_id,
                        agent_version_id=context.agent_version_id,
                        client_id=context.client_id,
                        payload={"call_id": tc.id, "success": tool_res.success, "data": tool_res.data, "error": tool_res.error}
                    )

                    res_str = json.dumps(tool_res.data if tool_res.success else {"error": tool_res.error})
                    context.conversation.add_tool_result(
                        tool_call_id=tc.id,
                        content=res_str,
                        tool_name=tc.tool_name
                    )

                t_tool_llm_start = time.perf_counter()
                llm_result = await llm_provider.generate_async(
                    system_instruction=context.conversation.system_instruction,
                    messages=context.conversation.to_llm_messages(),
                    available_tools=available_tools_list
                )
                t_tool_llm_done = time.perf_counter()
                llm_latency_ms += round((t_tool_llm_done - t_tool_llm_start) * 1000, 2)

                context.usage_tracker.record_llm(
                    llm_result.usage.get("input_tokens", 0),
                    llm_result.usage.get("output_tokens", 0)
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

            await websocket.send_json({
                "type": "assistant_text",
                "text": assistant_text
            })

            # Update session usage in DB
            session_record.usage_json = context.usage_tracker.get_summary()
            session_repo.update(session_record)

            # 3. Stream TTS Audio
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
            logger.error(f"Error during audio conversational turn: {e}")
            await websocket.send_json({"type": "error", "message": str(e)})
            emitter.emit(
                RuntimeEventType.SESSION_ERROR,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"error": str(e)}
            )
        finally:
            turn_in_progress = False

    try:
        # Initial greeting if defined
        has_dialogue = any(m.role.value in ("user", "assistant") for m in context.conversation.messages)
        if context.agent_spec.conversation.greeting and not has_dialogue:
            greeting_text = context.resolved_greeting or context.agent_spec.conversation.greeting
            context.conversation.add_assistant_message(content=greeting_text)
            emitter.emit(
                RuntimeEventType.ASSISTANT_RESPONSE,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"text": greeting_text, "is_greeting": True}
            )
            await websocket.send_json({"type": "assistant_text", "text": greeting_text})
            current_tts_task = asyncio.create_task(send_tts_stream(greeting_text))

        # Main Ingestion Loop
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            # Binary Audio Frame
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                if len(raw_bytes) > settings.MAX_AUDIO_FRAME_SIZE:
                    logger.warning(f"Audio frame exceeds max size limit ({len(raw_bytes)} bytes)")
                    continue

                # Voice activity & Barge-in detection
                has_energy = _is_voice_energy(raw_bytes, threshold=1200)
                if has_energy:
                    speech_energy_count += 1
                    if t_speech_start is None:
                        t_speech_start = time.perf_counter()

                    # Require several consecutive energetic frames before treating
                    # microphone input as a real turn. This filters silence, device
                    # noise, and echoed assistant audio from STT.
                    if speech_energy_count >= 3:
                        has_spoken = True

                    if speech_energy_count >= 5 and assistant_speaking:
                        # User started speaking over assistant -> Barge In!
                        await handle_interrupt(reason="barge_in")
                else:
                    speech_energy_count = max(0, speech_energy_count - 1)

                # Stream audio to active STT session if available (avoid feeding echo during assistant speech)
                if has_spoken and not assistant_speaking:
                    stt_stream = await ensure_streaming_stt()
                    if stt_stream:
                        await stt_stream.send_audio(raw_bytes)
                    audio_buffer.extend(raw_bytes)

            # JSON Control Message
            elif "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                    msg_type = payload.get("type", "")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "interrupt":
                        await handle_interrupt(reason="user_interrupt")

                    elif msg_type == "start":
                        audio_buffer.clear()
                        speech_energy_count = 0
                        has_spoken = False
                        t_speech_start = time.perf_counter()
                        t_stt_partial = None
                        t_speech_end = None
                        await ensure_streaming_stt()

                    elif msg_type == "stop":
                        t_speech_end = time.perf_counter()
                        if has_spoken and len(audio_buffer) > 0 and not turn_in_progress:
                            turn_bytes = bytes(audio_buffer)
                            audio_buffer.clear()
                            has_spoken = False
                            s_start = t_speech_start
                            s_end = t_speech_end
                            t_speech_start = None
                            t_stt_partial = None
                            asyncio.create_task(
                                execute_turn(
                                    turn_bytes,
                                    t_ref_speech_start=s_start,
                                    t_ref_speech_end=s_end
                                )
                            )
                        else:
                            audio_buffer.clear()
                            has_spoken = False

                    elif msg_type == "text_input":
                        input_txt = payload.get("text", "")
                        if input_txt and not turn_in_progress:
                            if assistant_speaking:
                                await handle_interrupt(reason="user_interrupt")
                            t_now = time.perf_counter()
                            asyncio.create_task(
                                execute_turn(
                                    input_txt.encode("utf-8"),
                                    t_ref_speech_start=t_now,
                                    t_ref_speech_end=t_now
                                )
                            )

                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON payload over audio WebSocket")

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for session '{session_id}'")
    except Exception as e:
        logger.error(f"WebSocket session error: {e}")
    finally:
        active_audio_sessions.discard(session_id)
        if current_tts_task and not current_tts_task.done():
            current_tts_task.cancel()
        if streaming_stt_session:
            try:
                await streaming_stt_session.close()
            except Exception:
                pass

        emitter.emit(
            RuntimeEventType.AUDIO_SESSION_DISCONNECTED,
            session_id=session_id,
            agent_id=context.agent_id if context else (session_record.agent_id if session_record else ""),
            agent_version_id=context.agent_version_id if context else (session_record.agent_version_id if session_record else ""),
            client_id=context.client_id if context else (session_record.client_id if session_record else "")
        )
