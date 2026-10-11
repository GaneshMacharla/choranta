import asyncio
import base64
import json
import logging
import struct
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set
from fastapi import WebSocket
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.repositories.call_repository import CallRepository
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.runtime.lifecycle import SessionStatus
from app.runtime.runtime import AgentRuntime
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony import TelephonyProvider

logger = logging.getLogger("choranta.runtime.telephony.session")

active_telephony_calls: Set[str] = set()


def _is_telephony_voice_energy(pcm16_bytes: bytes, threshold: int = 500) -> bool:
    """Computes RMS amplitude of 16kHz 16-bit PCM frame to detect speech energy on phone line."""
    count = len(pcm16_bytes) // 2
    if count == 0:
        return False
    try:
        shorts = struct.unpack(f"<{count}h", pcm16_bytes[:count * 2])
        rms = (sum(s * s for s in shorts) / count) ** 0.5
        return rms > threshold
    except Exception:
        return False


class TelephonyMediaSession:
    """
    Manages a live bidirectional telephony media stream between a phone caller and AgentRuntime.
    Transcodes between carrier PSTN audio (Exotel 8kHz PCM16) and canonical Choranta runtime audio (16kHz PCM16).
    Handles real-time STT streaming, Gemini LLM dialogue turns, streaming TTS playback,
    and phone-specific barge-in audio queue flushing.
    """

    def __init__(
        self,
        websocket: WebSocket,
        call_record: Call,
        stream_sid: str,
        db: Session,
        telephony_provider: TelephonyProvider,
        runtime: Optional[AgentRuntime] = None
    ):
        self.websocket = websocket
        self.call_record = call_record
        self.stream_sid = stream_sid
        self.db = db
        self.telephony_provider = telephony_provider
        self.runtime = runtime or AgentRuntime(db, registry=default_registry)
        self.emitter = EventEmitter(db)
        self.call_repo = CallRepository(db)
        self.session_repo = RuntimeSessionRepository(db)

        self.runtime_session: Optional[RuntimeSession] = None
        self.context = None
        self.streaming_stt_session = None

        self.assistant_speaking = False
        self.turn_in_progress = False
        self.current_tts_task: Optional[asyncio.Task] = None
        self.closed = False

        self.audio_buffer = bytearray()
        self.speech_energy_count = 0
        self.t_turn_speech_start: Optional[float] = None
        self.t_turn_speech_end: Optional[float] = None
        self.t_call_start = time.perf_counter()

    async def initialize(self) -> None:
        """Starts the active RuntimeSession and prepares the STT/TTS pipeline."""
        active_telephony_calls.add(self.call_record.id)

        # 1. Update Call status to ACTIVE / CONNECTED
        self.call_record.status = "ACTIVE"
        self.call_record.answered_at = datetime.now(timezone.utc)
        self.call_repo.update(self.call_record)

        self.emitter.emit(
            RuntimeEventType.TELEPHONY_MEDIA_CONNECTED,
            session_id=self.call_record.runtime_session_id or "",
            agent_id=self.call_record.agent_id,
            agent_version_id=self.call_record.agent_version_id,
            client_id=self.call_record.client_id,
            payload={
                "stream_sid": self.stream_sid,
                "provider_call_id": self.call_record.provider_call_id,
                "caller": self.call_record.caller_number,
                "destination": self.call_record.destination_number
            }
        )

        # 2. Get or start RuntimeSession
        session_id = self.call_record.runtime_session_id
        if session_id:
            self.runtime_session = self.session_repo.get_by_id(session_id)
            self.context = self.runtime._contexts.get(session_id)

        if not self.context and self.runtime_session:
            from app.models.agent_version import AgentVersion
            from app.schemas.agent_spec import CanonicalAgentSpec
            from app.runtime.context import RuntimeContext

            version = self.db.query(AgentVersion).filter(AgentVersion.id == self.runtime_session.agent_version_id).first()
            spec = CanonicalAgentSpec.model_validate(version.configuration_json)
            self.context = RuntimeContext(
                session_id=self.runtime_session.id,
                agent_id=self.runtime_session.agent_id,
                client_id=self.runtime_session.client_id,
                agent_version_id=self.runtime_session.agent_version_id,
                agent_spec=spec,
                metadata=self.runtime_session.metadata_
            )
            self.runtime._contexts[self.runtime_session.id] = self.context

        # 3. Trigger initial greeting if configured
        if self.context and self.context.agent_spec.conversation.greeting:
            greeting = self.context.resolved_greeting or self.context.agent_spec.conversation.greeting
            self.context.conversation.add_assistant_message(content=greeting)
            self.emitter.emit(
                RuntimeEventType.ASSISTANT_RESPONSE,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"text": greeting, "is_greeting": True}
            )
            self.current_tts_task = asyncio.create_task(self.send_tts_stream(greeting))

    async def on_stt_partial(self, partial_text: str):
        """Callback from streaming STT when partial speech is detected."""
        if not partial_text or not self.runtime_session or not self.context:
            return
        self.emitter.emit(
            RuntimeEventType.USER_TRANSCRIPT_PARTIAL,
            session_id=self.runtime_session.id,
            agent_id=self.context.agent_id,
            agent_version_id=self.context.agent_version_id,
            client_id=self.context.client_id,
            payload={"text": partial_text}
        )

    async def ensure_streaming_stt(self):
        if not self.streaming_stt_session and self.context:
            stt_provider = default_registry.get_stt(self.context.agent_spec.providers.stt)
            try:
                self.streaming_stt_session = await stt_provider.create_stream(
                    on_partial=self.on_stt_partial
                )
            except Exception as e:
                logger.warning(f"Could not create streaming STT session for call: {e}")
        return self.streaming_stt_session

    async def handle_barge_in(self):
        """Cancels outgoing assistant audio and tells the carrier to immediately clear caller playback buffer."""
        if not self.assistant_speaking and (not self.current_tts_task or self.current_tts_task.done()):
            return

        self.assistant_speaking = False
        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()

        # Send carrier clear command
        try:
            clear_msg = self.telephony_provider.build_clear_message(self.stream_sid)
            await self.websocket.send_text(clear_msg)
        except Exception as e:
            logger.warning(f"Error sending clear message to telephony provider: {e}")

        if self.runtime_session and self.context:
            self.emitter.emit(
                RuntimeEventType.ASSISTANT_INTERRUPTED,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"reason": "telephony_barge_in"}
            )

    async def send_tts_stream(self, text: str, t_ref_end: Optional[float] = None, stt_ms: float = 0.0, llm_ms: float = 0.0):
        """Streams synthesized assistant speech to the telephony channel."""
        self.assistant_speaking = True
        t_tts_start = time.perf_counter()
        t_tts_first_chunk: Optional[float] = None

        tts_provider = default_registry.get_tts(self.context.agent_spec.providers.tts)

        try:
            self.emitter.emit(
                RuntimeEventType.TTS_STARTED,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"text": text, "voice_id": self.context.agent_spec.voice.voice_id}
            )

            total_pcm_bytes = 0
            frame_size = self.telephony_provider.outbound_frame_bytes
            pending = bytearray()
            async for audio_chunk in tts_provider.synthesize_stream(
                text=text,
                voice_id=self.context.agent_spec.voice.voice_id,
                speed=self.context.agent_spec.voice.speed
            ):
                if not self.assistant_speaking:
                    logger.info("TTS streaming aborted due to telephony barge-in.")
                    break

                if audio_chunk:
                    if t_tts_first_chunk is None:
                        t_tts_first_chunk = time.perf_counter()
                        ttfb_ms = round((t_tts_first_chunk - t_tts_start) * 1000, 2)
                        round_trip_ms = round((t_tts_first_chunk - t_ref_end) * 1000, 2) if t_ref_end else None

                    # Transcode 16kHz PCM16 -> carrier format, framed to the carrier's chunk size
                    pending.extend(self.telephony_provider.normalize_audio_outbound(audio_chunk))
                    while pending and (not frame_size or len(pending) >= frame_size):
                        take = frame_size or len(pending)
                        frame = bytes(pending[:take])
                        del pending[:take]
                        await self.websocket.send_text(
                            self.telephony_provider.build_media_message(self.stream_sid, frame)
                        )

                    total_pcm_bytes += len(audio_chunk)
                    self.emitter.emit(
                        RuntimeEventType.TTS_AUDIO_CHUNK,
                        session_id=self.runtime_session.id,
                        agent_id=self.context.agent_id,
                        agent_version_id=self.context.agent_version_id,
                        client_id=self.context.client_id,
                        payload={"chunk_bytes": len(audio_chunk)}
                    )
                    await asyncio.sleep(0.001)

            if pending and self.assistant_speaking:
                if frame_size:
                    # Pad the tail with silence to a 320-byte (20ms) boundary
                    pending.extend(b"\x00" * (-len(pending) % 320))
                await self.websocket.send_text(
                    self.telephony_provider.build_media_message(self.stream_sid, bytes(pending))
                )

            duration = total_pcm_bytes / (16000 * 2)
            self.context.usage_tracker.record_tts(duration)
            self.emitter.emit(
                RuntimeEventType.TTS_COMPLETED,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"duration_seconds": duration, "interrupted": not self.assistant_speaking}
            )
        except asyncio.CancelledError:
            logger.info("Telephony TTS task cancelled.")
        except Exception as e:
            logger.error(f"Error streaming TTS over telephony: {e}")
        finally:
            self.assistant_speaking = False

    async def execute_turn(self, pcm16_audio_bytes: bytes, t_start: Optional[float] = None, t_end: Optional[float] = None):
        """Processes caller audio into STT, runs LLM, and streams back assistant audio."""
        if self.turn_in_progress or not self.context or not self.runtime_session:
            return
        self.turn_in_progress = True

        t_ref_end = t_end or time.perf_counter()
        stt_provider = default_registry.get_stt(self.context.agent_spec.providers.stt)
        llm_provider = default_registry.get_llm(self.context.agent_spec.providers.llm)

        try:
            self.emitter.emit(
                RuntimeEventType.USER_SPEECH_STARTED,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id
            )

            # 1. Finalize STT
            if self.streaming_stt_session:
                transcript_res = await self.streaming_stt_session.finish()
                self.streaming_stt_session = None
            else:
                transcript_res = await stt_provider.process_audio_async(pcm16_audio_bytes)

            t_stt_done = time.perf_counter()
            stt_latency_ms = round((t_stt_done - t_ref_end) * 1000, 2)
            user_text = transcript_res.text.strip()
            self.context.usage_tracker.record_stt(len(pcm16_audio_bytes) / (16000 * 2))

            self.emitter.emit(
                RuntimeEventType.USER_TRANSCRIPT_FINAL,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"text": user_text, "confidence": transcript_res.confidence, "latency_ms": stt_latency_ms}
            )

            if not user_text:
                return

            self.context.conversation.add_user_message(user_text)

            # 2. Invoke LLM & Tools
            t_llm_start = time.perf_counter()
            self.emitter.emit(
                RuntimeEventType.LLM_REQUEST_STARTED,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id
            )

            available_tools_list = [{"name": t, "id": t} for t in self.context.active_tools]
            llm_result = await llm_provider.generate_async(
                system_instruction=self.context.conversation.system_instruction,
                messages=self.context.conversation.to_llm_messages(),
                available_tools=available_tools_list
            )

            t_llm_done = time.perf_counter()
            llm_latency_ms = round((t_llm_done - t_llm_start) * 1000, 2)
            self.context.usage_tracker.record_llm(
                llm_result.usage.get("input_tokens", 0),
                llm_result.usage.get("output_tokens", 0)
            )

            self.emitter.emit(
                RuntimeEventType.LLM_RESPONSE,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"latency_ms": llm_latency_ms, "finish_reason": llm_result.finish_reason}
            )

            # Tool Loop
            if llm_result.tool_calls:
                self.context.conversation.add_assistant_message(
                    content=llm_result.text,
                    tool_calls=[tc.model_dump() for tc in llm_result.tool_calls]
                )

                for tc in llm_result.tool_calls:
                    self.emitter.emit(
                        RuntimeEventType.TOOL_CALL_STARTED,
                        session_id=self.runtime_session.id,
                        agent_id=self.context.agent_id,
                        agent_version_id=self.context.agent_version_id,
                        client_id=self.context.client_id,
                        payload={"call_id": tc.id, "tool_name": tc.tool_name, "arguments": tc.arguments}
                    )

                    tool_res = self.runtime.tool_executor.execute_tool(
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        enabled_tool_ids=self.context.active_tools
                    )

                    self.emitter.emit(
                        RuntimeEventType.TOOL_CALL_COMPLETED,
                        session_id=self.runtime_session.id,
                        agent_id=self.context.agent_id,
                        agent_version_id=self.context.agent_version_id,
                        client_id=self.context.client_id,
                        payload={"call_id": tc.id, "success": tool_res.success, "data": tool_res.data, "error": tool_res.error}
                    )

                    res_str = json.dumps(tool_res.data if tool_res.success else {"error": tool_res.error})
                    self.context.conversation.add_tool_result(
                        tool_call_id=tc.id,
                        content=res_str,
                        tool_name=tc.tool_name
                    )

                llm_result = await llm_provider.generate_async(
                    system_instruction=self.context.conversation.system_instruction,
                    messages=self.context.conversation.to_llm_messages(),
                    available_tools=available_tools_list
                )
                self.context.usage_tracker.record_llm(
                    llm_result.usage.get("input_tokens", 0),
                    llm_result.usage.get("output_tokens", 0)
                )

            assistant_text = llm_result.text or self.context.agent_spec.conversation.fallback_response
            self.context.conversation.add_assistant_message(content=assistant_text)

            self.emitter.emit(
                RuntimeEventType.ASSISTANT_RESPONSE,
                session_id=self.runtime_session.id,
                agent_id=self.context.agent_id,
                agent_version_id=self.context.agent_version_id,
                client_id=self.context.client_id,
                payload={"text": assistant_text}
            )

            # Update session usage in DB
            self.runtime_session.usage_json = self.context.usage_tracker.get_summary()
            self.session_repo.update(self.runtime_session)

            # 3. Stream TTS to caller
            self.current_tts_task = asyncio.create_task(
                self.send_tts_stream(
                    assistant_text,
                    t_ref_end=t_ref_end,
                    stt_ms=stt_latency_ms,
                    llm_ms=llm_latency_ms
                )
            )
            await self.current_tts_task

        except Exception as e:
            logger.error(f"Error in telephony conversation turn: {e}")
        finally:
            self.turn_in_progress = False

    async def handle_media_payload(self, payload_b64: str) -> None:
        """Processes an incoming media frame from the telephony provider."""
        try:
            carrier_bytes = base64.b64decode(payload_b64)
        except Exception:
            return

        pcm16_bytes = self.telephony_provider.normalize_audio_inbound(carrier_bytes)
        if not pcm16_bytes:
            return

        # Voice energy & barge-in
        has_energy = _is_telephony_voice_energy(pcm16_bytes)
        if has_energy:
            self.speech_energy_count += 1
            if self.t_turn_speech_start is None:
                self.t_turn_speech_start = time.perf_counter()

            if self.speech_energy_count >= 2 and self.assistant_speaking:
                await self.handle_barge_in()
        else:
            self.speech_energy_count = max(0, self.speech_energy_count - 1)

        # Stream audio frame to active STT session
        stt_stream = await self.ensure_streaming_stt()
        if stt_stream:
            await stt_stream.send_audio(pcm16_bytes)

        self.audio_buffer.extend(pcm16_bytes)

        # If silence is maintained after speech, conclude turn automatically
        # (the carrier streams continuous audio; 800ms silence concludes the turn)
        if self.speech_energy_count == 0 and len(self.audio_buffer) >= 6400 and not self.turn_in_progress:
            # 6400 bytes = 200ms audio buffer minimum
            turn_pcm = bytes(self.audio_buffer)
            self.audio_buffer.clear()
            s_start = self.t_turn_speech_start
            s_end = time.perf_counter()
            self.t_turn_speech_start = None
            asyncio.create_task(
                self.execute_turn(turn_pcm, t_start=s_start, t_end=s_end)
            )

    async def close(self, reason: str = "normal") -> None:
        """Terminates active telephony session, ends runtime, and updates call record."""
        if self.closed:
            return
        self.closed = True

        active_telephony_calls.discard(self.call_record.id)

        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()

        if self.streaming_stt_session:
            try:
                await self.streaming_stt_session.close()
            except Exception:
                pass

        # Update Call record
        now = datetime.now(timezone.utc)
        self.call_record.status = "COMPLETED"
        self.call_record.ended_at = now
        call_duration = max(0.0, time.perf_counter() - self.t_call_start)
        self.call_record.duration_seconds = round(call_duration, 2)
        self.call_record.termination_reason = reason
        self.call_repo.update(self.call_record)

        # End RuntimeSession
        if self.runtime_session:
            try:
                self.runtime.end_session(self.runtime_session.id)
            except Exception:
                pass

        self.emitter.emit(
            RuntimeEventType.TELEPHONY_MEDIA_DISCONNECTED,
            session_id=self.call_record.runtime_session_id or "",
            agent_id=self.call_record.agent_id,
            agent_version_id=self.call_record.agent_version_id,
            client_id=self.call_record.client_id,
            payload={"reason": reason, "duration_seconds": self.call_record.duration_seconds}
        )

        self.emitter.emit(
            RuntimeEventType.CALL_COMPLETED,
            session_id=self.call_record.runtime_session_id or "",
            agent_id=self.call_record.agent_id,
            agent_version_id=self.call_record.agent_version_id,
            client_id=self.call_record.client_id,
            payload={"call_id": self.call_record.id, "duration_seconds": self.call_record.duration_seconds}
        )
