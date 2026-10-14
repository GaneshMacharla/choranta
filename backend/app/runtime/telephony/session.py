import asyncio
import base64
import json
import logging
import os
import threading
import time
import weakref
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from fastapi import WebSocket
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.core.config import settings
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.repositories.call_repository import CallRepository
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.runtime.conversation import ConversationRole
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.runtime.runtime import AgentRuntime
from app.runtime.call_limits import CallLimits, resolve_call_limits
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony import TelephonyProvider
from app.runtime.telephony.endpointing import SpeechEndpointer, EndpointerConfig
from app.runtime.telephony.speech_text import SentenceChunker, clean_for_speech, is_backchannel, pause_hint
from app.runtime.telephony import phrases
from app.runtime.speech_style import VOICE_STYLE_INSTRUCTIONS, VOICE_STYLE_MARKER, apply_voice_style
from app.schemas.agent_spec import ConversationSpec
from app.runtime.tools.catalog import describe_tools
from app.runtime.telephony.recorder import CallRecorder
from app.runtime.telephony import tts_cache
from app.runtime import call_rules

logger = logging.getLogger("choranta.runtime.telephony.session")

active_telephony_calls: Set[str] = set()
# Post-call work (output extraction) kept referenced until it finishes
_background_tasks: Set[asyncio.Task] = set()

# Audio already handed to the carrier but not yet played; small so interruptions are near-instant
PLAYBACK_LEAD_MS = 250
# Events are written to the database in the background at this interval (never on the audio path)
EVENT_FLUSH_INTERVAL_S = 0.5
# Speaking-rate estimate used to work out how much of a sentence the caller heard before cutting in
CHARS_PER_SECOND = 15.0
# Transcription starts after 250 ms of silence and is reused if the caller stays quiet until the
# turn ends (VOICE_END_SILENCE_MS), which hides most of the speech-to-text time
EARLY_TRANSCRIBE_MS = 250


def _endpointer_config() -> EndpointerConfig:
    return EndpointerConfig(end_silence_ms=settings.VOICE_END_SILENCE_MS, early_transcribe_ms=EARLY_TRANSCRIBE_MS)


# Appended to the agent's instructions on phone calls (shared with browser test calls)
PHONE_STYLE_MARKER = VOICE_STYLE_MARKER
PHONE_STYLE_INSTRUCTIONS = VOICE_STYLE_INSTRUCTIONS
END_CALL_TOOL = call_rules.END_CALL_TOOL
# The schema's stock fallback; agents that keep it get a natural, localized line instead
STOCK_FALLBACK_RESPONSE = ConversationSpec.model_fields["fallback_response"].default
# When the agent's voice provider fails mid-call (outage, out of credits), sentences are spoken with this one
TTS_FALLBACK_PROVIDER = "sarvam"

# During the greeting, short caller replies ("Hello?", "Haan", "Who is this?") don't cancel it
GREETING_IGNORE_MAX_WORDS = 4

# Speech provider requests in flight across all calls, capped at the plan's concurrency limit
_provider_slots: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _speech_provider_slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    slot = _provider_slots.get(loop)
    if slot is None:
        slot = asyncio.Semaphore(max(1, settings.CARTESIA_MAX_CONCURRENCY))
        _provider_slots[loop] = slot
    return slot


class FillerText(str):
    """A line said to fill a silence ("One moment, let me check."): played, never added to the conversation."""

    def __new__(cls, text: str, kind: str):
        obj = super().__new__(cls, text)
        obj.kind = kind
        return obj


class _SpokenSentence:
    """One sentence of a reply: its synthesized carrier audio and when it was played."""

    def __init__(self, text: str, filler_kind: Optional[str] = None):
        self.text = text
        self.filler_kind = filler_kind  # "tool_filler" / "slow_ack" for filler lines, else None
        self.counted = False
        self.audio = bytearray()        # carrier-format audio, filled as TTS streams in
        self.done = False               # synthesis finished
        self.updated = asyncio.Event()
        self.play_start: Optional[float] = None
        self.play_end: Optional[float] = None  # when the last sent frame finishes playing
        self.finished_sending = False


class _AssistantTurn:
    """State of the agent's current reply (or greeting), used to commit what the caller actually heard."""

    def __init__(self):
        self.sentences: List[_SpokenSentence] = []
        self.full_text_parts: List[str] = []
        self.committed = False
        self.started_audio = False
        self.is_greeting = False
        self.t_reference: Optional[float] = None  # caller speech end, for latency logging
        self.stt_ms: Optional[int] = None
        self.first_token_ms: Optional[int] = None
        self.queued_reply = False   # a sentence of the actual reply has been queued
        self.tool_filler_said = False


class TelephonyMediaSession:
    """
    Real-time phone conversation between a caller and an AgentRuntime session.

    - Caller audio (carrier 8kHz PCM16) is endpointed into complete utterances, then transcribed.
    - Replies stream from the LLM; each sentence is synthesized as soon as it is complete and played
      while later sentences are still being generated and synthesized.
    - Audio is paced to real time, so when the caller cuts in the carrier buffer is flushed and only
      what the caller actually heard is kept in the conversation (marked as interrupted).
    - A false interruption (noise, cough, or a backchannel like "okay"/"haan") resumes the reply.
    - Runtime events are persisted in the background, never on the audio path.
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

        self.assistant_speaking = False
        self.closed = False
        self.t_call_start = time.perf_counter()

        # Caller speech endpointing: utterances are complete phrases, never silence or noise
        self.endpointer = SpeechEndpointer(_endpointer_config())
        self._utterance_queue: "asyncio.Queue[bytes]" = asyncio.Queue()
        self._early_transcript: Optional[asyncio.Task] = None
        self._utterance_worker: Optional[asyncio.Task] = None

        # Reply state
        self._turn_task: Optional[asyncio.Task] = None
        self._turn: Optional[_AssistantTurn] = None
        self._paused = False
        self._pause_time: Optional[float] = None
        self._resume_event = asyncio.Event()
        self._play_clock = 0.0  # monotonic time at which audio already sent to the carrier ends

        self._flush_task: Optional[asyncio.Task] = None
        self._pending_writes: List[asyncio.Task] = []

        # Stereo call recording (caller left, agent right), saved when the call ends
        self.recorder = CallRecorder(start_time=time.monotonic())

        # Call control: agent hang-up, silence handling, maximum duration
        self._tool_defs: List[Dict[str, Any]] = []
        self._end_call_requested = False
        self._end_reason: Optional[str] = None
        self._last_activity = time.monotonic()
        self._reprompted = False
        self._wrapping_up = False
        self._processing_utterance = False
        self._watchdog_task: Optional[asyncio.Task] = None

        # Canned lines said on this call (so the next one differs) and conversation-quality counters
        self._phrase_history: Dict[str, str] = {}
        self._latencies_ms: List[int] = []
        self._fillers_played: Dict[str, int] = {"tool_filler": 0, "slow_ack": 0}
        self._barge_ins = 0
        self._false_barge_ins = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Marks the call active, attaches the runtime session and plays the greeting."""
        active_telephony_calls.add(self.call_record.id)
        self.recorder = CallRecorder(start_time=time.monotonic())

        self.call_record.status = "ACTIVE"
        self.call_record.answered_at = datetime.now(timezone.utc)
        self.call_repo.update(self.call_record)

        session_id = self.call_record.runtime_session_id
        if session_id:
            self.runtime_session = self.session_repo.get_by_id(session_id)
            self.context = self.runtime._contexts.get(session_id)

        if not self.context and self.runtime_session:
            self.context = self.runtime._load_context(self.runtime_session)

        if self.context:
            self._apply_phone_style()
            self._tool_defs = describe_tools(self.db, self.context.active_tools) + [END_CALL_TOOL]

        # From here on, events are buffered and written in the background
        self.emitter.start_buffering()
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._utterance_worker = asyncio.create_task(self._utterance_loop())
        self._last_activity = time.monotonic()
        self._watchdog_task = asyncio.create_task(self._watchdog())

        self._emit(RuntimeEventType.TELEPHONY_MEDIA_CONNECTED, {
            "stream_sid": self.stream_sid,
            "provider_call_id": self.call_record.provider_call_id,
            "caller": self.call_record.caller_number,
            "destination": self.call_record.destination_number
        })

        if self.context and self.context.agent_spec.conversation.greeting:
            greeting = self.context.resolved_greeting or self.context.agent_spec.conversation.greeting
            self._start_turn(self._speak_text(greeting, is_greeting=True))

    async def close(self, reason: str = "normal") -> None:
        """Terminates the call: stops speaking, flushes events, ends the runtime session."""
        if self.closed:
            return
        self.closed = True
        reason = self._end_reason or reason
        active_telephony_calls.discard(self.call_record.id)

        for task in (self._turn_task, self._utterance_worker, self._watchdog_task):
            if task and not task.done():
                task.cancel()
        for task in (self._turn_task, self._utterance_worker, self._watchdog_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        now = datetime.now(timezone.utc)
        self.call_record.status = "COMPLETED"
        self.call_record.ended_at = now
        self.call_record.duration_seconds = round(max(0.0, time.perf_counter() - self.t_call_start), 2)
        self.call_record.termination_reason = reason
        await self._save_recording()
        self.call_repo.update(self.call_record)

        self._emit(RuntimeEventType.TELEPHONY_MEDIA_DISCONNECTED, {
            "reason": reason, "duration_seconds": self.call_record.duration_seconds
        })
        self._emit(RuntimeEventType.CALL_COMPLETED, {
            "call_id": self.call_record.id, "duration_seconds": self.call_record.duration_seconds,
            "conversation_quality": self.conversation_quality(),
        })

        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        await self._flush_events()
        if self._pending_writes:
            await asyncio.gather(*self._pending_writes, return_exceptions=True)

        if self.runtime_session:
            try:
                self.runtime.end_session(self.runtime_session.id)
            except Exception as e:
                logger.warning(f"Could not end runtime session {self.runtime_session.id}: {e}")

        # Debit the client's prepaid wallet (after end_session, so the final usage is known)
        try:
            from app.services.billing import charge_call
            charge_call(self.db, self.call_record)
        except Exception as e:
            logger.error(f"Could not charge call {self.call_record.id}: {type(e).__name__}: {e}")

        # Fill in the agent's output variables from the transcript, off the call path
        if settings.ENVIRONMENT != "test":
            try:
                from app.db.session import SessionLocal
                from app.services import call_outputs
                if call_outputs.mark_pending(self.db, self.call_record):
                    task = asyncio.create_task(
                        asyncio.to_thread(call_outputs.run_extraction_job, SessionLocal, self.call_record.id)
                    )
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
            except Exception as e:
                logger.error(f"Could not start output extraction for call {self.call_record.id}: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Inbound audio
    # ------------------------------------------------------------------

    async def handle_media_payload(self, payload_b64: str) -> None:
        """Processes an incoming media frame from the telephony provider."""
        try:
            carrier_bytes = base64.b64decode(payload_b64)
        except Exception:
            return

        self.recorder.add_caller_audio(carrier_bytes)
        pcm16_bytes = self.telephony_provider.normalize_audio_inbound(carrier_bytes)
        if not pcm16_bytes:
            return

        for event in self.endpointer.process(pcm16_bytes):
            if event.kind in ("speech_start", "utterance"):
                self._mark_caller_activity()
            if event.kind == "speech_start":
                if self._is_playing():
                    await self.handle_barge_in()
            elif event.kind == "speech_discarded":
                # It was only noise: carry on with the reply
                if self._paused:
                    logger.info("False interruption (noise); resuming the agent's reply.")
                    self._resume()
            elif event.kind == "pause":
                self._cancel_early_transcript()
                if self.context:
                    self._early_transcript = asyncio.create_task(self._transcribe(event.audio))
            elif event.kind == "utterance":
                logger.info(f"Caller utterance detected ({event.speech_ms:.0f} ms of speech).")
                early = self._early_transcript if event.same_as_pause else None
                if early is None:
                    self._cancel_early_transcript()
                self._early_transcript = None
                await self.execute_turn(event.audio, t_end=time.perf_counter(), early_transcript=early)

    def _cancel_early_transcript(self) -> None:
        if self._early_transcript and not self._early_transcript.done():
            self._early_transcript.cancel()
        self._early_transcript = None

    async def _transcribe(self, audio: bytes):
        stt_provider = default_registry.get_stt(self.context.agent_spec.providers.stt)
        async with _speech_provider_slot():
            return await stt_provider.process_audio_async(audio)

    async def execute_turn(
        self,
        pcm16_audio_bytes: bytes,
        t_start: Optional[float] = None,
        t_end: Optional[float] = None,
        early_transcript: Optional[asyncio.Task] = None,
    ):
        """Queues one complete caller utterance; utterances are handled strictly in order."""
        if self.closed:
            return
        await self._utterance_queue.put((pcm16_audio_bytes, t_end or time.perf_counter(), early_transcript))

    async def _utterance_loop(self) -> None:
        while not self.closed:
            audio, t_end, early_transcript = await self._utterance_queue.get()
            try:
                await self._handle_utterance(audio, t_end, early_transcript)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error handling caller utterance: {type(e).__name__}: {e}")

    async def _handle_utterance(self, audio: bytes, t_end: float, early_transcript: Optional[asyncio.Task] = None) -> None:
        if not self.context or not self.runtime_session:
            return
        self._processing_utterance = True
        try:
            await self._handle_utterance_inner(audio, t_end, early_transcript)
        finally:
            self._processing_utterance = False
            self._last_activity = time.monotonic()

    async def _handle_utterance_inner(self, audio: bytes, t_end: float, early_transcript: Optional[asyncio.Task] = None) -> None:
        transcript = None
        if early_transcript is not None:
            try:
                transcript = await early_transcript
            except (asyncio.CancelledError, Exception) as e:
                logger.info(f"Early transcription unavailable ({type(e).__name__}); transcribing the full utterance.")
        if transcript is None:
            transcript = await self._transcribe(audio)
        user_text = (transcript.text or "").strip()
        self.context.usage_tracker.record_stt(len(audio) / (16000 * 2))
        stt_ms = round((time.perf_counter() - t_end) * 1000)

        if not user_text:
            logger.info("Caller utterance had no words; ignoring.")
            if self._paused:
                self._resume()
            return

        if self._paused and is_backchannel(user_text):
            logger.info(f"Backchannel '{user_text}' while agent was speaking; resuming.")
            self._resume()
            return

        greeting_active = bool(
            self._turn and self._turn.is_greeting and self._turn_task and not self._turn_task.done()
        )
        if greeting_active and len(user_text.split()) <= GREETING_IGNORE_MAX_WORDS:
            # Callers say "Hello?" on pickup; the greeting itself answers that
            logger.info(f"Caller said '{user_text}' during the greeting; continuing the greeting.")
            self._emit(RuntimeEventType.USER_TRANSCRIPT_FINAL, {
                "text": user_text, "confidence": transcript.confidence, "latency_ms": stt_ms
            })
            if self._paused:
                self._resume()
            return

        self._emit(RuntimeEventType.USER_TRANSCRIPT_FINAL, {
            "text": user_text, "confidence": transcript.confidence, "latency_ms": stt_ms
        })

        thinking = bool(
            self._turn and not self._turn.started_audio and self._turn_task and not self._turn_task.done()
        )
        if thinking and is_backchannel(user_text):
            # "Hello?" while the reply is being prepared: restarting would only delay it further
            logger.info(f"Caller said '{user_text}' while the agent was preparing a reply; keeping the reply.")
            return

        # A new caller turn replaces whatever the agent was saying or preparing
        await self._interrupt_current_turn()
        self._add_user_text(user_text)
        if self.limits.matches_end_call_phrase(user_text):
            # "Not interested", "bye": say goodbye without paying for an LLM round
            logger.info(f"Caller said end-call phrase '{user_text}'; hanging up.")
            self._say_then_hang_up(self._farewell(), "end_call_phrase")
            return
        self._start_turn(self._respond_when_done(t_end, user_text, stt_ms))

    async def _respond_when_done(self, t_end: float, user_text: str, stt_ms: Optional[int] = None) -> None:
        """
        Replies once the caller has finished. If they trailed off mid-thought ("my budget is...", half a
        phone number), waits a little first: if they carry on, their next words cancel this turn and are
        merged into the same message, so the agent answers the whole thought once.
        """
        if self._turn:
            self._turn.stt_ms = stt_ms
        hint = pause_hint(user_text)
        # A clear sign they'll carry on ("my budget is...") waits the full hold; a weak one (a Telugu/Hindi
        # phrase ending on a case ending) waits half, so short complete answers stay quick
        hold_ms = settings.VOICE_INCOMPLETE_HOLD_MS * (1.0 if hint == "strong" else 0.5 if hint == "weak" else 0.0)
        if hold_ms > 0:
            logger.info(f"Caller may not have finished ('{user_text[-40:]}', {hint}); waiting {hold_ms:.0f} ms.")
            await asyncio.sleep(hold_ms / 1000.0)
            while self.endpointer.in_speech:  # they carried on: their utterance will replace this turn
                await asyncio.sleep(0.05)
        await self._respond(t_end)

    # ------------------------------------------------------------------
    # Interruptions
    # ------------------------------------------------------------------

    def _is_playing(self) -> bool:
        return bool(self._turn and self._turn.started_audio and not self._paused and self._turn_task and not self._turn_task.done())

    async def handle_barge_in(self):
        """Caller started talking over the agent: flush carrier audio and pause the reply."""
        if not self.assistant_speaking and not self._is_playing():
            return
        self._paused = True
        self._barge_ins += 1
        self._resume_event.clear()
        self._pause_time = time.monotonic()
        self.assistant_speaking = False
        self._play_clock = self._pause_time
        self.recorder.discard_agent_after(self._pause_time)
        try:
            await self.websocket.send_text(self.telephony_provider.build_clear_message(self.stream_sid))
        except Exception as e:
            logger.warning(f"Error sending clear message to telephony provider: {e}")
        self._emit(RuntimeEventType.ASSISTANT_INTERRUPTED, {"reason": "telephony_barge_in"})

    def _resume(self) -> None:
        if self._paused:
            self._false_barge_ins += 1  # noise or "haan": the reply carries on
        self._paused = False
        self._pause_time = None
        self._resume_event.set()

    async def _interrupt_current_turn(self) -> None:
        task, turn = self._turn_task, self._turn
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # The turn's cancellation is expected; our own (the call is closing) must propagate
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception:
                pass
        if turn and not turn.committed:
            self._commit_turn(turn, interrupted=True)
        self._turn_task = None
        self._turn = None
        self._paused = False
        self._pause_time = None
        self._resume_event.set()
        self.assistant_speaking = False

    # ------------------------------------------------------------------
    # Replies
    # ------------------------------------------------------------------

    def _start_turn(self, coro) -> None:
        self._turn = _AssistantTurn()
        self._paused = False
        self._resume_event.set()
        self._turn_task = asyncio.create_task(self._run_turn(self._turn, coro))

    async def _run_turn(self, turn: _AssistantTurn, coro) -> None:
        try:
            await coro
            if not turn.committed:
                self._commit_turn(turn, interrupted=False)
            if self._end_call_requested and self._turn is turn:
                await self._hang_up()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in telephony reply: {type(e).__name__}: {e}")
            if not turn.committed:
                self._commit_turn(turn, interrupted=True)
        finally:
            if self._turn is turn:
                self.assistant_speaking = False
                self._last_activity = time.monotonic()

    async def _speak_text(self, text: str, is_greeting: bool = False) -> None:
        turn = self._turn
        turn.is_greeting = is_greeting
        queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        chunker = SentenceChunker()
        for chunk in chunker.feed(text) + chunker.flush():
            await queue.put(chunk)
        await queue.put(None)
        turn.full_text_parts.append(text)
        await self._play_sentences(turn, queue)

    async def _respond(self, t_reference: float) -> None:
        """Streams the LLM reply sentence by sentence into speech, running tools as requested."""
        turn = self._turn
        turn.t_reference = t_reference
        llm = default_registry.get_llm(self.context.agent_spec.providers.llm)
        tools = self._tool_defs or [END_CALL_TOOL]
        limits = self.limits
        max_chars = max(0, limits.max_reply_chars)
        queued_chars = 0
        capped = False

        sentences: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        player = asyncio.create_task(self._play_sentences(turn, sentences))
        chunker = SentenceChunker()

        async def put(sentence: str) -> None:
            turn.queued_reply = True
            await sentences.put(sentence)

        ack = (
            asyncio.create_task(self._slow_reply_ack(turn, sentences))
            if settings.VOICE_SLOW_REPLY_ACK_MS > 0 else None
        )
        try:
            self._emit(RuntimeEventType.LLM_REQUEST_STARTED, {})
            t_llm = time.perf_counter()
            first_token_ms = None
            rounds = 0
            while True:
                final = None
                messages = self.context.conversation.to_llm_messages()
                stream = _iterate_in_thread(
                    llm.generate_stream,
                    system_instruction=self.context.instruction_for_turn(),
                    messages=messages,
                    available_tools=tools if rounds < limits.max_tool_rounds else None,
                )
                streamed_text: List[str] = []
                try:
                    async for item in stream:
                        if isinstance(item, str):
                            if first_token_ms is None:
                                first_token_ms = round((time.perf_counter() - t_llm) * 1000)
                                turn.first_token_ms = first_token_ms
                            streamed_text.append(item)
                            turn.full_text_parts.append(item)
                            for sentence in chunker.feed(item):
                                await put(sentence)
                                queued_chars += len(sentence)
                            if max_chars and queued_chars >= max_chars:
                                # Long-winded reply: stop after the sentence that crossed the cap
                                capped = True
                                break
                        else:
                            final = item
                finally:
                    await stream.aclose()
                if final is not None:
                    self.context.usage_tracker.record_llm(
                        final.usage.get("input_tokens", 0), final.usage.get("output_tokens", 0)
                    )
                elif capped:
                    # Stopped early: estimate tokens so the call cost isn't understated
                    prompt_chars = len(self.context.conversation.system_instruction) + sum(len(str(m.get("content") or "")) for m in messages)
                    self.context.usage_tracker.record_llm(prompt_chars // 4, len("".join(streamed_text)) // 4)
                if capped:
                    logger.info(f"Agent reply capped at {queued_chars} characters.")
                    break
                if final is None or not final.tool_calls or rounds >= limits.max_tool_rounds:
                    break

                if any(tc.tool_name == "end_call" for tc in final.tool_calls):
                    # The agent is wrapping up: say goodbye (if it hasn't) and hang up after speaking
                    self._end_call_requested = True
                    self.context.conversation.add_assistant_message(
                        content=final.text,
                        tool_calls=[tc.model_dump() for tc in final.tool_calls]
                    )
                    for tc in final.tool_calls:
                        self.context.conversation.add_tool_result(
                            tool_call_id=tc.id, content=json.dumps({"ok": True}), tool_name=tc.tool_name
                        )
                    self._emit(RuntimeEventType.TOOL_CALL_COMPLETED, {"tool_name": "end_call", "success": True})
                    for sentence in chunker.flush():
                        await put(sentence)
                        queued_chars += len(sentence)
                    if not queued_chars:
                        farewell = self._farewell()
                        turn.full_text_parts.append(farewell)
                        await put(farewell)
                    break

                # Tool round: speak any lead-in text first, then run the tools
                for sentence in chunker.flush():
                    await put(sentence)
                if settings.VOICE_TOOL_FILLER and not turn.tool_filler_said and not "".join(streamed_text).strip():
                    # Don't leave the caller in silence while the tool runs
                    turn.tool_filler_said = True
                    await sentences.put(FillerText(self._phrase("tool_filler"), "tool_filler"))
                rounds += 1
                self.context.conversation.add_assistant_message(
                    content=final.text,
                    tool_calls=[tc.model_dump() for tc in final.tool_calls]
                )
                for tc in final.tool_calls:
                    self._emit(RuntimeEventType.TOOL_CALL_STARTED, {
                        "call_id": tc.id, "tool_name": tc.tool_name, "arguments": tc.arguments
                    })
                    t_tool = time.perf_counter()
                    result = await asyncio.to_thread(
                        self.runtime.tool_executor.execute_tool,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=self.context.with_contact_details(tc.tool_name, tc.arguments),
                        enabled_tool_ids=self.context.active_tools,
                        client_id=self.context.client_id
                    )
                    self._emit(RuntimeEventType.TOOL_CALL_COMPLETED, {
                        "call_id": tc.id, "success": result.success, "data": result.data, "error": result.error,
                        "duration_ms": round((time.perf_counter() - t_tool) * 1000),
                    })
                    self.context.conversation.add_tool_result(
                        tool_call_id=tc.id,
                        content=json.dumps(result.data if result.success else {"error": result.error}),
                        tool_name=tc.tool_name
                    )
                # Text spoken before the tool call is already in the conversation
                turn.full_text_parts.clear()

            if not capped:
                for sentence in chunker.flush():
                    await put(sentence)
            if not "".join(turn.full_text_parts).strip():
                fallback = self._fallback_text()
                turn.full_text_parts.append(fallback)
                await put(fallback)
            self._emit(RuntimeEventType.LLM_RESPONSE, {"first_token_ms": first_token_ms, "tool_rounds": rounds})
            await sentences.put(None)
            await player
        finally:
            if ack and not ack.done():
                ack.cancel()
            if not player.done():
                player.cancel()
                try:
                    await player
                except (asyncio.CancelledError, Exception):
                    pass

    async def _slow_reply_ack(self, turn: _AssistantTurn, sentences: "asyncio.Queue[Optional[str]]") -> None:
        """Says a short "Okay." when the reply is slow to start, so the caller isn't left in silence."""
        try:
            await asyncio.sleep(settings.VOICE_SLOW_REPLY_ACK_MS / 1000.0)
        except asyncio.CancelledError:
            return
        if turn.queued_reply or turn.sentences or self.endpointer.in_speech or self._paused:
            return
        await sentences.put(FillerText(self._phrase("slow_ack"), "slow_ack"))

    def _language(self) -> str:
        spec = self.context.agent_spec if self.context else None
        return (spec.languages.primary if spec and spec.languages else None) or "en"

    def _phrase(self, kind: str) -> str:
        """A canned line in the agent's language, never the same variant twice in a row on this call."""
        return phrases.pick(kind, self._language(), self._phrase_history)

    def _fallback_text(self) -> str:
        custom = (self.context.agent_spec.conversation.fallback_response or "").strip()
        if custom and custom != STOCK_FALLBACK_RESPONSE:
            return custom  # an operator wrote this agent's own fallback
        return self._phrase("fallback")

    async def _play_sentences(self, turn: _AssistantTurn, sentences: "asyncio.Queue[Optional[str]]") -> None:
        """
        Plays sentences strictly in order, synthesizing only the current one and the next
        VOICE_PREFETCH_SENTENCES: audio prepared for a sentence the caller never hears is still billed.
        """
        tts = default_registry.get_tts(self.context.agent_spec.providers.tts)
        synth_tasks: Dict[int, asyncio.Task] = {}
        all_queued = asyncio.Event()
        new_sentence = asyncio.Event()
        prefetch = max(0, settings.VOICE_PREFETCH_SENTENCES)

        async def collect() -> None:
            while True:
                text = await sentences.get()
                if text is None:
                    break
                filler_kind = text.kind if isinstance(text, FillerText) else None
                text = clean_for_speech(text)
                if not text:
                    continue
                turn.sentences.append(_SpokenSentence(text, filler_kind))
                new_sentence.set()
            all_queued.set()
            new_sentence.set()

        def ensure_synthesis(upto: int) -> None:
            for i in range(min(upto + 1, len(turn.sentences))):
                if i not in synth_tasks:
                    synth_tasks[i] = asyncio.create_task(self._synthesize(tts, turn.sentences[i]))

        collector = asyncio.create_task(collect())
        index = 0
        try:
            while True:
                if index < len(turn.sentences):
                    ensure_synthesis(index + prefetch)
                    await self._play_sentence(turn, turn.sentences[index], lambda: ensure_synthesis(index + prefetch))
                    index += 1
                    continue
                if all_queued.is_set():
                    break
                new_sentence.clear()
                if index >= len(turn.sentences) and not all_queued.is_set():
                    await new_sentence.wait()
        finally:
            for task in [collector, *synth_tasks.values()]:
                if not task.done():
                    task.cancel()

    async def _synthesize(self, tts, sentence: _SpokenSentence) -> None:
        spec = self.context.agent_spec
        key = tts_cache.cache_key(
            spec.providers.tts, spec.voice.voice_id, spec.voice.speed, spec.languages.primary,
            type(self.telephony_provider).__name__, sentence.text,
        )
        try:
            cached = tts_cache.get(key)
            if cached is not None:
                # Said before in this voice: replay it, nothing is billed
                sentence.audio.extend(cached)
                sentence.updated.set()
                return
            # Sentences queue for a provider slot in order, so the next one to play goes first
            async with _speech_provider_slot():
                async for chunk in tts.synthesize_stream(
                    text=sentence.text,
                    voice_id=spec.voice.voice_id,
                    speed=spec.voice.speed,
                    language=spec.languages.primary
                ):
                    if chunk:
                        sentence.audio.extend(self.telephony_provider.normalize_audio_outbound(chunk))
                        sentence.updated.set()
            self.context.usage_tracker.record_tts(len(sentence.audio) / 16000.0, characters=len(sentence.text))
            tts_cache.put(key, bytes(sentence.audio))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"TTS failed for sentence: {type(e).__name__}: {e}")
            if not sentence.audio and spec.providers.tts != TTS_FALLBACK_PROVIDER:
                # e.g. Cartesia out of credits: say it in a Sarvam voice rather than leave the caller in silence
                await self._synthesize_fallback(sentence)
        finally:
            sentence.done = True
            sentence.updated.set()

    async def _synthesize_fallback(self, sentence: _SpokenSentence) -> None:
        spec = self.context.agent_spec
        try:
            fallback = default_registry.get_tts(TTS_FALLBACK_PROVIDER)
            async with _speech_provider_slot():
                async for chunk in fallback.synthesize_stream(
                    text=sentence.text, voice_id=None, speed=spec.voice.speed, language=spec.languages.primary
                ):
                    if chunk:
                        sentence.audio.extend(self.telephony_provider.normalize_audio_outbound(chunk))
                        sentence.updated.set()
            logger.warning(f"Spoke a sentence with the {TTS_FALLBACK_PROVIDER} voice after {spec.providers.tts} failed.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Fallback TTS failed too: {type(e).__name__}: {e}")

    async def _play_sentence(self, turn: _AssistantTurn, sentence: _SpokenSentence, on_wait=None) -> None:
        """Sends one sentence's audio paced to real time; restarts it after a false interruption."""
        frame_bytes = self.telephony_provider.outbound_frame_bytes or 3200
        pos = 0
        while True:
            if on_wait:
                on_wait()  # newly arrived sentences may now be within the prefetch window
            if self._paused:
                await self._resume_event.wait()
                # The carrier buffer was flushed: replay this sentence from the start
                pos = 0
                sentence.play_start = None
                continue

            # Don't start talking over a caller who is mid-sentence
            if pos == 0 and self.endpointer.in_speech:
                await asyncio.sleep(0.05)
                continue

            available = len(sentence.audio) - pos
            if available >= frame_bytes or (sentence.done and available > 0):
                take = min(frame_bytes, available)
                frame = bytes(sentence.audio[pos:pos + take])
                if take < frame_bytes:
                    frame += b"\x00" * (-len(frame) % 320)
                await self._send_frame(turn, sentence, frame)
                pos += take
                continue

            if sentence.done:
                sentence.finished_sending = True
                return

            sentence.updated.clear()
            if len(sentence.audio) - pos < frame_bytes and not sentence.done:
                await sentence.updated.wait()

    async def _send_frame(self, turn: _AssistantTurn, sentence: _SpokenSentence, frame: bytes) -> None:
        now = time.monotonic()
        frame_ms = len(frame) / 16.0  # carrier audio: 8kHz 16-bit = 16 bytes per ms
        start = max(now, self._play_clock)
        if sentence.play_start is None:
            sentence.play_start = start
        if sentence.filler_kind and not sentence.counted:
            sentence.counted = True
            self._fillers_played[sentence.filler_kind] = self._fillers_played.get(sentence.filler_kind, 0) + 1
        self._play_clock = start + frame_ms / 1000.0
        sentence.play_end = self._play_clock

        if not turn.started_audio:
            turn.started_audio = True
            if turn.t_reference:
                latency = round((time.perf_counter() - turn.t_reference) * 1000)
                logger.info(f"Agent started speaking {latency} ms after the caller finished.")
                self._latencies_ms.append(latency)
                self._emit(RuntimeEventType.TTS_STARTED, {
                    "response_latency_ms": latency,
                    "stt_ms": turn.stt_ms,
                    "llm_first_token_ms": turn.first_token_ms,
                    "first_audio_filler": sentence.filler_kind or "none",
                })
        self.assistant_speaking = True

        await self.websocket.send_text(self.telephony_provider.build_media_message(self.stream_sid, frame))
        self.recorder.add_agent_audio(frame, start)

        lead = self._play_clock - time.monotonic()
        if lead * 1000 > PLAYBACK_LEAD_MS:
            await asyncio.sleep(lead - PLAYBACK_LEAD_MS / 1000.0)

    # ------------------------------------------------------------------
    # Call control
    # ------------------------------------------------------------------

    def _apply_phone_style(self) -> None:
        # Human speaking style, plus staying on the business's topic
        apply_voice_style(self.context.conversation, self.context.agent_spec)

    @property
    def limits(self) -> CallLimits:
        """This agent's call limits, with platform defaults for anything it leaves unset."""
        return resolve_call_limits(self.context.agent_spec if self.context else None)

    def _farewell(self) -> str:
        # The agent's own farewell, already in the call's language; else a localized default
        farewell = (getattr(self.context, "resolved_farewell", "") or "").strip() if self.context else ""
        return farewell or self._phrase("default_farewell")

    def _mark_caller_activity(self) -> None:
        self._last_activity = time.monotonic()
        self._reprompted = False

    def _is_idle(self) -> bool:
        turn_running = self._turn_task is not None and not self._turn_task.done()
        return not (
            turn_running or self._processing_utterance or self.endpointer.in_speech
            or not self._utterance_queue.empty() or self._paused
        )

    async def _hang_up(self, reason: str = "agent_ended") -> None:
        """Lets the last words finish playing, then ends the call by closing the media stream."""
        self._end_reason = self._end_reason or reason
        await asyncio.sleep(max(0.0, self._play_clock - time.monotonic()) + 0.4)
        # Don't cut off a caller who is still talking (e.g. saying goodbye back)
        deadline = time.monotonic() + 3.0
        while self.endpointer.in_speech and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        logger.info(f"Hanging up call {self.call_record.id} ({self._end_reason}).")
        try:
            await self.websocket.close()
        except Exception:
            pass

    def _say_then_hang_up(self, text: str, reason: str) -> None:
        self._end_call_requested = True
        self._end_reason = reason
        self._start_turn(self._speak_text(text))

    async def _watchdog(self) -> None:
        """Handles caller silence and the maximum call length."""
        try:
            while not self.closed:
                await asyncio.sleep(0.5)
                if self._end_call_requested or not self.context:
                    continue
                if not self._is_idle():
                    continue
                limits = self.limits
                elapsed = time.perf_counter() - self.t_call_start
                if limits.max_call_duration_s and elapsed >= limits.max_call_duration_s:
                    logger.info(f"Call {self.call_record.id} reached the maximum duration; wrapping up.")
                    self._say_then_hang_up(self._farewell(), "max_duration")
                    continue
                silent = time.monotonic() - self._last_activity
                if not self._reprompted and silent >= limits.silence_reprompt_s:
                    self._reprompted = True
                    self._start_turn(self._speak_text(self._phrase("reprompt")))
                elif self._reprompted and silent >= limits.silence_hangup_s:
                    logger.info(f"Caller silent on call {self.call_record.id}; hanging up.")
                    self._say_then_hang_up(self._phrase("silence_goodbye"), "caller_silent")
        except asyncio.CancelledError:
            pass

    def conversation_quality(self) -> Dict[str, Any]:
        """How human the call felt: reply latency, fillers used and interruptions."""
        latencies = sorted(self._latencies_ms)
        return {
            "turns": len(latencies),
            "avg_response_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            "p90_response_latency_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.9))] if latencies else None,
            "max_response_latency_ms": latencies[-1] if latencies else None,
            "fillers_played": dict(self._fillers_played),
            "barge_ins": self._barge_ins,
            "false_barge_ins": self._false_barge_ins,
        }

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def _save_recording(self) -> None:
        """Writes the stereo WAV to RECORDINGS_DIR and links it from the call's metadata."""
        try:
            wav_bytes = self.recorder.to_wav()
            if not wav_bytes:
                return
            directory = settings.RECORDINGS_DIR
            path = os.path.join(directory, f"{self.call_record.id}.wav")

            def write() -> None:
                os.makedirs(directory, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(wav_bytes)

            await asyncio.to_thread(write)
            metadata = dict(self.call_record.metadata_ or {})
            metadata["recording_file"] = f"{self.call_record.id}.wav"
            metadata["recording_duration_seconds"] = round(self.recorder.duration_seconds, 2)
            self.call_record.metadata_ = metadata
            flag_modified(self.call_record, "metadata_")
            logger.info(f"Saved call recording ({self.recorder.duration_seconds:.1f}s) to {path}")
        except Exception as e:
            logger.error(f"Failed to save call recording for {self.call_record.id}: {type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Conversation bookkeeping
    # ------------------------------------------------------------------

    def _heard_text(self, turn: _AssistantTurn, interrupted: bool) -> str:
        # Fillers ("One moment, let me check.") were said, but aren't part of the agent's reply
        reply = [s for s in turn.sentences if not s.filler_kind]
        if not interrupted:
            return " ".join(s.text for s in reply) or "".join(turn.full_text_parts).strip()
        cutoff = self._pause_time or time.monotonic()
        heard: List[str] = []
        for sentence in reply:
            if sentence.play_start is None or sentence.play_start >= cutoff:
                break
            if sentence.finished_sending and sentence.play_end and sentence.play_end <= cutoff:
                heard.append(sentence.text)
                continue
            # Partially heard: estimate how far through the sentence playback got
            total_s = (len(sentence.audio) / 16000.0) if sentence.done and sentence.audio else len(sentence.text) / CHARS_PER_SECOND
            fraction = min(1.0, max(0.0, (cutoff - sentence.play_start) / max(total_s, 0.1)))
            cut = int(len(sentence.text) * fraction)
            partial = sentence.text[:cut].rsplit(" ", 1)[0] if " " in sentence.text[:cut] else ""
            if partial:
                heard.append(partial)
            break
        return " ".join(heard).strip()

    def _commit_turn(self, turn: _AssistantTurn, interrupted: bool) -> None:
        turn.committed = True
        if not self.context:
            return
        heard = self._heard_text(turn, interrupted)
        if not heard:
            return
        content = f"{heard}... [interrupted by caller]" if interrupted else heard
        self.context.conversation.add_assistant_message(content=content)
        self._emit(RuntimeEventType.ASSISTANT_RESPONSE, {"text": heard, "interrupted": interrupted})

    def _add_user_text(self, text: str) -> None:
        """Adds the caller's words; merges with an unanswered previous utterance."""
        messages = self.context.conversation.messages
        if messages and messages[-1].role == ConversationRole.USER:
            messages[-1].content = f"{messages[-1].content} {text}".strip()
        else:
            self.context.conversation.add_user_message(text)

    # ------------------------------------------------------------------
    # Background event persistence
    # ------------------------------------------------------------------

    def _emit(self, event_type: RuntimeEventType, payload: Dict[str, Any]) -> None:
        session_id = (self.runtime_session.id if self.runtime_session else None) or self.call_record.runtime_session_id or ""
        self.emitter.emit(
            event_type,
            session_id=session_id,
            agent_id=self.call_record.agent_id,
            agent_version_id=self.call_record.agent_version_id,
            client_id=self.call_record.client_id,
            payload=payload
        )

    async def _flush_loop(self) -> None:
        try:
            while not self.closed:
                await asyncio.sleep(EVENT_FLUSH_INTERVAL_S)
                await self._flush_events()
        except asyncio.CancelledError:
            pass

    async def _flush_events(self) -> None:
        records = self.emitter.drain_buffer()
        if not self.closed:
            self.emitter.start_buffering()
        if not records:
            return
        bind = self.db.get_bind()

        def write() -> None:
            db = Session(bind=bind)
            try:
                db.add_all(records)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to persist {len(records)} call events: {type(e).__name__}: {e}")
            finally:
                db.close()

        task = asyncio.create_task(asyncio.to_thread(write))
        self._pending_writes = [t for t in self._pending_writes if not t.done()] + [task]
        await task


async def _iterate_in_thread(fn, **kwargs) -> AsyncIterator[Any]:
    """Runs a blocking generator in a worker thread and yields its items without blocking the event loop."""
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue" = asyncio.Queue()
    stop = threading.Event()

    def run() -> None:
        def put(item):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                pass
        try:
            for item in fn(**kwargs):
                if stop.is_set():
                    break
                put(("item", item))
        except Exception as e:
            put(("error", e))
        finally:
            put(("end", None))

    loop.run_in_executor(None, run)
    try:
        while True:
            kind, value = await queue.get()
            if kind == "item":
                yield value
            elif kind == "error":
                raise value
            else:
                return
    finally:
        stop.set()
