import asyncio
import base64
import inspect
import re
import json
import logging
import os
import threading
import time
import weakref
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from fastapi import WebSocket
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.runtime.conversation import compact_json
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
from app.runtime.providers.registry import ProviderRegistry, default_registry
from app.runtime.providers.telephony import TelephonyProvider
from app.runtime.providers.tts import TextFeed
from app.runtime.telephony.endpointing import SpeechEndpointer, EndpointerConfig
from app.runtime.telephony.speech_text import (
    SentenceChunker, clean_for_speech, is_backchannel, is_presence_check, pause_hint, speech_language,
)
from app.runtime.telephony import phrases
from app.runtime.speech_style import VOICE_STYLE_INSTRUCTIONS, VOICE_STYLE_MARKER, apply_voice_style
from app.schemas.agent_spec import ConversationSpec
from app.runtime.tools.catalog import describe_tools
from app.runtime.telephony.recorder import CallRecorder
from app.runtime.telephony import tts_cache
from app.runtime import call_rules
from app.services.call_costing import estimate_call_cost

logger = logging.getLogger("choranta.runtime.telephony.session")

# Credit budget guard: the agent starts wrapping up when the call, this many seconds from now plus a
# cushion for the closing words, would cost more than its budget; past the budget it hangs up at once
BUDGET_LOOKAHEAD_S = 20.0
BUDGET_CUSHION_SHARE = 0.1

active_telephony_calls: Set[str] = set()
# Post-call work (output extraction) kept referenced until it finishes
_background_tasks: Set[asyncio.Task] = set()

# Audio already handed to the carrier but not yet played; small so interruptions are near-instant
PLAYBACK_LEAD_MS = 250
# Events are written to the database in the background at this interval (never on the audio path)
EVENT_FLUSH_INTERVAL_S = 0.5
# Speaking-rate estimate used to work out how much of a sentence the caller heard before cutting in
CHARS_PER_SECOND = 15.0
# Sarvam closes idle connections after ~30 s; a light request this often keeps them open for the next reply
KEEP_WARM_INTERVAL_S = 10.0
# Transcription starts after 250 ms of silence and is reused if the caller stays quiet until the
# turn ends (VOICE_END_SILENCE_MS), which hides most of the speech-to-text time
EARLY_TRANSCRIBE_MS = 250


def _endpointer_config() -> EndpointerConfig:
    return EndpointerConfig(
        end_silence_ms=settings.VOICE_END_SILENCE_MS,
        early_transcribe_ms=EARLY_TRANSCRIBE_MS,
        min_energy=settings.VOICE_MIN_SPEECH_ENERGY,
    )


# Appended to the agent's instructions on phone calls (shared with browser test calls)
PHONE_STYLE_MARKER = VOICE_STYLE_MARKER
PHONE_STYLE_INSTRUCTIONS = VOICE_STYLE_INSTRUCTIONS
END_CALL_TOOL = call_rules.END_CALL_TOOL
# The schema's stock fallback; agents that keep it get a natural, localized line instead
STOCK_FALLBACK_RESPONSE = ConversationSpec.model_fields["fallback_response"].default
# When the agent's voice provider fails mid-call (outage, out of credits), sentences are spoken with this one
TTS_FALLBACK_PROVIDER = "sarvam"

# The agent stops talking for the caller only once this much pitched sound (a voice) is heard: loud rumble,
# breath or wind on the mic has almost none, so it no longer cuts the agent off
BARGE_IN_PITCHED_MS = 120

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


# Resuming after a false interruption: pick up at the last pause between phrases at most this far back
RESUME_LOOKBACK_S = 3.0
RESUME_GAP_MS = 140        # silence at least this long counts as a pause between phrases
RESUME_LEAD_IN_MS = 60     # resume this far into the pause, so the phrase doesn't start abruptly


def phrase_start(pcm: bytes, position: int, sample_rate: int) -> int:
    """
    Byte offset in 16-bit mono `pcm` to resume playback from when it stopped at `position`: the end of the
    last pause between phrases before it (less a short lead-in), or 0 to start over when there is none.
    """
    if position <= 0:
        return 0
    samples = np.frombuffer(pcm[: position - position % 2], dtype=np.int16).astype(np.float32)
    frame = max(1, sample_rate // 50)  # 20 ms
    frames = len(samples) // frame
    if frames == 0:
        return 0
    rms = np.sqrt(np.mean(samples[: frames * frame].reshape(frames, frame) ** 2, axis=1))
    quiet = rms < max(200.0, 0.08 * float(rms.max()))
    needed = max(1, RESUME_GAP_MS // 20)
    oldest = max(0, frames - int(RESUME_LOOKBACK_S * 50))
    run = 0
    for i in range(frames - 1, oldest - 1, -1):
        if quiet[i]:
            run += 1
            continue
        if run >= needed:
            gap_end = i + 1 + run  # first loud frame after the pause
            return max(0, gap_end * frame - sample_rate * RESUME_LEAD_IN_MS // 1000) * 2
        run = 0
    return 0


class FillerText(str):
    """A line said to fill a silence ("One moment, let me check."): played, never added to the conversation."""

    def __new__(cls, text: str, kind: str):
        obj = super().__new__(cls, text)
        obj.kind = kind
        return obj


class WholeText(str):
    """Text known in full up front (greeting, farewell, canned lines): spoken as one utterance, and cached."""


# Queued between the parts of a reply that are spoken separately (e.g. the lead-in before a tool runs): the
# open utterance is finished there, rather than waiting on text that won't come until the tool is done
SEGMENT_END = object()

# Longest canned text spoken as one utterance; longer text is split into sentences
WHOLE_TEXT_MAX_CHARS = 400


class _SpokenSentence:
    """
    One utterance of a reply: a sentence, or with a provider that voices text as it streams in, every
    sentence of the reply in one language (`feed` set: text keeps arriving until the feed is closed).
    Holds its synthesized carrier audio and when it was played.
    """

    def __init__(self, text: str, filler_kind: Optional[str] = None, language: Optional[str] = None,
                 feed: Optional[TextFeed] = None):
        self.text = text
        self.language = language
        self.feed = feed
        self.filler_kind = filler_kind  # "tool_filler" / "slow_ack" for filler lines, else None
        self.counted = False
        self.audio = bytearray()        # carrier-format audio, filled as TTS streams in
        self.done = False               # synthesis finished
        self.updated = asyncio.Event()
        self.play_start: Optional[float] = None
        self.play_end: Optional[float] = None  # when the last sent frame finishes playing
        self.finished_sending = False

    def add_text(self, text: str) -> None:
        """More of a streamed utterance's text, as the LLM writes it."""
        self.text = f"{self.text} {text}"
        self.feed.put(text)


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

    # A phone call is the whole session; a reconnectable transport (the audio WebSocket) keeps it open
    end_runtime_session_on_close = True

    def __init__(
        self,
        websocket: Optional[WebSocket],
        call_record: Call,
        stream_sid: str,
        db: Session,
        telephony_provider: TelephonyProvider,
        runtime: Optional[AgentRuntime] = None,
        registry: Optional[ProviderRegistry] = None,
    ):
        self.websocket = websocket
        self.call_record = call_record
        self.stream_sid = stream_sid
        self.db = db
        self.telephony_provider = telephony_provider
        # Speech and AI providers for this call (voice test runs bring their own; live calls use the shared one)
        self.registry = registry or default_registry
        self.runtime = runtime or AgentRuntime(db, registry=self.registry)
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
        # Live speech-to-text (when the provider has it): the caller's words are transcribed as they speak
        self._live_stt: Any = None
        self._live_segment: Any = None

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
        self.recorder = CallRecorder(start_time=time.monotonic(), sample_rate=self._carrier_rate)

        # Call control: agent hang-up, silence handling, maximum duration
        self._tool_defs: List[Dict[str, Any]] = []
        self._end_call_requested = False
        self._end_reason: Optional[str] = None
        self._last_activity = time.monotonic()
        self._reprompted = False
        self._wrapping_up = False
        self._processing_utterance = False
        self._watchdog_task: Optional[asyncio.Task] = None
        self._budget_pricing: Any = None

        # Canned lines said on this call (so the next one differs) and conversation-quality counters
        self._phrase_history: Dict[str, str] = {}
        self._latencies_ms: List[int] = []
        self._fillers_played: Dict[str, int] = {"tool_filler": 0, "slow_ack": 0}
        self._barge_ins = 0
        self._false_barge_ins = 0

    @property
    def _carrier_rate(self) -> int:
        """Sample rate of the carrier's audio: 8kHz on phone lines, 16kHz on browser test calls."""
        return getattr(self.telephony_provider, "carrier_sample_rate", 8000) or 8000

    @property
    def _carrier_bytes_per_second(self) -> float:
        return self._carrier_rate * 2.0

    def _native_rate_kwargs(self, tts) -> Dict[str, int]:
        """{'sample_rate': carrier rate} when the voice provider can speak at the carrier's rate itself, so its
        audio goes out as produced instead of being resampled by us (which muffles phone audio)."""
        rate = self._carrier_rate
        return {"sample_rate": rate} if rate in getattr(tts, "native_sample_rates", ()) else {}

    def _carrier_audio(self, chunk: bytes, native: bool) -> bytes:
        return chunk if native else self.telephony_provider.normalize_audio_outbound(chunk)

    def _sentence_language(self, text: str) -> Optional[str]:
        languages = self.context.agent_spec.languages
        return speech_language(text, languages.primary, languages.supported)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Marks the call active, attaches the runtime session and plays the greeting."""
        active_telephony_calls.add(self.call_record.id)
        self.recorder = CallRecorder(start_time=time.monotonic(), sample_rate=self._carrier_rate)

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

        self._start_live_stt()
        self._warm_connections()
        keep_warm = asyncio.create_task(self._keep_warm_loop())
        _background_tasks.add(keep_warm)
        keep_warm.add_done_callback(_background_tasks.discard)
        if self.context and self.context.agent_spec.conversation.greeting and self._should_greet():
            greeting = self.context.resolved_greeting or self.context.agent_spec.conversation.greeting
            self._start_turn(self._speak_text(greeting, is_greeting=True))

    def _should_greet(self) -> bool:
        return True

    async def _keep_warm_loop(self) -> None:
        try:
            while not self.closed:
                await asyncio.sleep(KEEP_WARM_INTERVAL_S)
                if not self.closed:
                    self._warm_connections()
        except asyncio.CancelledError:
            pass

    def _start_live_stt(self) -> None:
        """Opens live speech-to-text for the call when the provider supports it (else per-utterance REST)."""
        if not self.context or not settings.VOICE_LIVE_STT or settings.ENVIRONMENT == "test":
            return
        try:
            provider = self.registry.get_stt(self.context.agent_spec.providers.stt)
            factory = getattr(provider, "live_transcriber", None)
            if callable(factory):
                self._live_stt = factory(language=self._stt_language())
                self._live_stt.start()
        except Exception as e:
            logger.warning(f"Live speech-to-text unavailable ({type(e).__name__}: {e}); transcribing per utterance.")
            self._live_stt = None

    def _warm_connections(self) -> None:
        """Opens the speech-to-text, AI model and voice connections in the background, so a reply doesn't
        wait for a (sometimes slow) connection to be set up."""
        if not self.context or settings.ENVIRONMENT == "test":
            return
        spec = self.context.agent_spec
        for kind in ("stt", "llm", "tts"):
            try:
                provider = getattr(self.registry, f"get_{kind}")(getattr(spec.providers, kind))
            except Exception:
                continue
            warm = getattr(provider, "warm", None)
            if not callable(warm):
                continue
            kwargs = (
                {"voice_id": spec.voice.voice_id, "speed": spec.voice.speed, "language": spec.languages.primary,
                 **self._native_rate_kwargs(provider)}
                if kind == "tts" else {}
            )
            job = warm(**kwargs) if asyncio.iscoroutinefunction(warm) else asyncio.to_thread(warm, **kwargs)
            task = asyncio.create_task(job)
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

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
        if self._live_stt is not None:
            try:
                await self._live_stt.close()
            except Exception:
                pass
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

        if self.runtime_session and self.end_runtime_session_on_close:
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
        await self.handle_carrier_audio(carrier_bytes)

    async def handle_carrier_audio(self, carrier_bytes: bytes) -> None:
        """Processes one frame of caller audio in the carrier's format (16-bit PCM at the carrier's rate)."""
        self.recorder.add_caller_audio(carrier_bytes)
        pcm16_bytes = self.telephony_provider.normalize_audio_inbound(carrier_bytes)
        if not pcm16_bytes:
            return

        live = self._live_stt
        if live is not None and self._live_segment is not None and self.endpointer.in_speech:
            live.send(self._live_segment, pcm16_bytes)

        for event in self.endpointer.process(pcm16_bytes):
            # Silence handling pauses while the caller is talking (see _is_idle); only words reset it
            if event.kind == "speech_start":
                if live is not None:
                    self._live_segment = live.begin(event.audio)
                if self._is_playing() and self._caller_talking():
                    await self.handle_barge_in()
            elif event.kind == "speech_discarded":
                self._live_segment = None
                # It was only noise: carry on with the reply
                if self._paused:
                    logger.info("False interruption (noise); resuming the agent's reply.")
                    self._resume()
            elif event.kind == "pause":
                # Live transcription is already under way; otherwise start transcribing before the turn ends
                if live is None:
                    self._cancel_early_transcript()
                    if self.context:
                        self._early_transcript = asyncio.create_task(self._transcribe(event.audio))
            elif event.kind == "utterance":
                logger.info(f"Caller utterance detected ({event.speech_ms:.0f} ms of speech).")
                if live is not None and self._live_segment is not None:
                    early = asyncio.create_task(self._live_transcript(self._live_segment, event.audio))
                    self._live_segment = None
                else:
                    early = self._early_transcript if event.same_as_pause else None
                    if early is None:
                        self._cancel_early_transcript()
                    self._early_transcript = None
                await self.execute_turn(event.audio, t_end=time.perf_counter(), early_transcript=early)
        # Sound that started as possible noise becomes an interruption once it is clearly a voice
        if self._is_playing() and self._caller_talking():
            await self.handle_barge_in()

    def _caller_talking(self) -> bool:
        """The caller is speaking now: sustained sound that is pitched like a voice, not just loud."""
        return self.endpointer.in_speech and self.endpointer.pitched_ms >= BARGE_IN_PITCHED_MS

    def _cancel_early_transcript(self) -> None:
        if self._early_transcript and not self._early_transcript.done():
            self._early_transcript.cancel()
        self._early_transcript = None

    async def _live_transcript(self, segment, audio: bytes):
        """The live transcript of an utterance, or the REST one when the live result isn't usable."""
        result = await self._live_stt.finish(segment)
        return result if result is not None else await self._transcribe(audio)

    async def _transcribe(self, audio: bytes):
        stt_provider = self.registry.get_stt(self.context.agent_spec.providers.stt)
        language = self._stt_language()
        async with _speech_provider_slot():
            if language and "language" in inspect.signature(stt_provider.process_audio_async).parameters:
                return await stt_provider.process_audio_async(audio, language=language)
            return await stt_provider.process_audio_async(audio)

    def _stt_language(self) -> Optional[str]:
        """The agent's language when it speaks only one: auto-detect misreads short or quiet clips (Telugu
        heard as English). Agents that switch languages keep auto-detect."""
        languages = self.context.agent_spec.languages if self.context else None
        if not languages:
            return None
        spoken = {code.split("-")[0].lower() for code in [languages.primary, *(languages.supported or [])] if code}
        return languages.primary if len(spoken) == 1 else None

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
            # Noise, a cough or line hiss: not the caller answering, so it doesn't reset silence handling
            logger.info("Caller utterance had no words; ignoring.")
            if self._paused:
                self._resume()
            return
        self._mark_caller_activity()

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

        if is_presence_check(user_text) and not self._is_playing():
            # "Hello? Are you there?": reassure and repeat the open question, without paying for an LLM round
            question = self._last_question()
            reply = self._phrase("still_here") + (f" {question}" if question else "")
            logger.info(f"Caller checked the line ('{user_text}'); answering without the LLM.")
            await self._interrupt_current_turn()
            self._add_user_text(user_text)
            self._start_turn(self._speak_text(reply))
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

    async def handle_text_input(self, text: str) -> None:
        """A typed caller turn (testing over the audio WebSocket): same handling as a transcribed utterance."""
        text = (text or "").strip()
        if self.closed or not text or not self.context or not self.runtime_session:
            return
        self._mark_caller_activity()
        self._emit(RuntimeEventType.USER_TRANSCRIPT_FINAL, {"text": text, "typed": True})
        await self._interrupt_current_turn()
        self._add_user_text(text)
        if self.limits.matches_end_call_phrase(text):
            self._say_then_hang_up(self._farewell(), "end_call_phrase")
            return
        self._start_turn(self._respond(time.perf_counter()))

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
            await self._clear_carrier_playback()
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
        if len(text) <= WHOLE_TEXT_MAX_CHARS:
            # One utterance: its sentences flow together, and the audio is cached whole (greetings recur)
            await queue.put(WholeText(text))
        else:
            chunker = SentenceChunker()
            for chunk in chunker.feed(text) + chunker.flush():
                await queue.put(WholeText(chunk))
        await queue.put(None)
        turn.full_text_parts.append(text)
        await self._play_sentences(turn, queue)

    async def _respond(self, t_reference: float) -> None:
        """Streams the LLM reply sentence by sentence into speech, running tools as requested."""
        turn = self._turn
        turn.t_reference = t_reference
        llm = self.registry.get_llm(self.context.agent_spec.providers.llm)
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
                        # Ended without a word (often "not interested"): a neutral goodbye, not the agent's
                        # farewell, which may promise a follow-up the caller just turned down
                        farewell = self._phrase("default_farewell")
                        turn.full_text_parts.append(farewell)
                        await put(farewell)
                    break

                # Tool round: speak any lead-in text first, then run the tools
                for sentence in chunker.flush():
                    await put(sentence)
                await sentences.put(SEGMENT_END)  # the lead-in is said now, not after the tool returns
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
                        content=compact_json(result.data if result.success else {"error": result.error}),
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
        if turn.queued_reply or turn.sentences or self._caller_talking() or self._paused:
            return
        await sentences.put(FillerText(self._phrase("slow_ack"), "slow_ack"))

    def _language(self) -> str:
        spec = self.context.agent_spec if self.context else None
        return (spec.languages.primary if spec and spec.languages else None) or "en"

    def _last_question(self) -> str:
        """The question the agent last asked, if its last reply ended on one (to repeat after "Hello?")."""
        if not self.context:
            return ""
        for m in reversed(self.context.conversation.messages):
            if m.role == ConversationRole.USER:
                return ""  # the caller has spoken since: nothing open to repeat
            if m.role == ConversationRole.ASSISTANT and (m.content or "").strip():
                last = re.split(r"(?<=[.!?।])\s+", m.content.strip())[-1]
                return last if last.endswith("?") else ""
        return ""

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
        Plays utterances strictly in order, synthesizing only the current one and the next
        VOICE_PREFETCH_SENTENCES: audio prepared for a sentence the caller never hears is still billed.

        With a voice that takes text as it streams (Sarvam), a reply's sentences go into one utterance as the
        LLM writes them, so they are voiced together like a person talking: intonation carries from one
        sentence to the next and there are no clip-sized gaps between them. Fillers, canned lines, a change
        of language and SEGMENT_END start a new utterance.
        """
        tts = self.registry.get_tts(self.context.agent_spec.providers.tts)
        streams_text = bool(getattr(tts, "supports_text_stream", False))
        synth_tasks: Dict[int, asyncio.Task] = {}
        all_queued = asyncio.Event()
        new_sentence = asyncio.Event()
        prefetch = max(0, settings.VOICE_PREFETCH_SENTENCES)
        open_unit: Optional[_SpokenSentence] = None  # streamed utterance still taking the reply's text

        def close_open_unit() -> None:
            nonlocal open_unit
            if open_unit is not None:
                open_unit.feed.close()
                open_unit = None

        async def collect() -> None:
            nonlocal open_unit
            try:
                while True:
                    item = await sentences.get()
                    if item is None:
                        break
                    if item is SEGMENT_END:
                        close_open_unit()
                        continue
                    filler_kind = item.kind if isinstance(item, FillerText) else None
                    whole = isinstance(item, WholeText)
                    text = clean_for_speech(item)
                    if not text:
                        continue
                    language = self._sentence_language(text)
                    if streams_text and not filler_kind and not whole:
                        if open_unit is not None and open_unit.language == language:
                            open_unit.add_text(text)
                            if open_unit.play_start is not None:
                                self._on_sentence_text(turn, open_unit, text)
                            continue
                        close_open_unit()
                        open_unit = _SpokenSentence(text, language=language, feed=TextFeed(text))
                        unit = open_unit
                    else:
                        close_open_unit()
                        unit = _SpokenSentence(text, filler_kind, language=language)
                    turn.sentences.append(unit)
                    new_sentence.set()
            finally:
                close_open_unit()
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

    def _tts_cache_key(self, sentence: _SpokenSentence, language: Optional[str]) -> tuple:
        spec = self.context.agent_spec
        return tts_cache.cache_key(
            spec.providers.tts, spec.voice.voice_id, spec.voice.speed, language,
            type(self.telephony_provider).__name__, sentence.text,
        )

    async def _synthesize(self, tts, sentence: _SpokenSentence) -> None:
        spec = self.context.agent_spec
        language = sentence.language or self._sentence_language(sentence.text)
        native = self._native_rate_kwargs(tts)
        try:
            if sentence.feed is not None:
                # Streamed utterance: its text is still arriving, so it can't come from the cache. Sarvam
                # has its own concurrency limits; the shared slot (sized for Cartesia) isn't held while the
                # LLM is still writing.
                chunks = tts.synthesize_text_stream(
                    sentence.feed, voice_id=spec.voice.voice_id, speed=spec.voice.speed, language=language, **native,
                )
                async for chunk in chunks:
                    if chunk:
                        sentence.audio.extend(self._carrier_audio(chunk, bool(native)))
                        sentence.updated.set()
            else:
                key = self._tts_cache_key(sentence, language)
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
                        language=language,
                        **native,
                    ):
                        if chunk:
                            sentence.audio.extend(self._carrier_audio(chunk, bool(native)))
                            sentence.updated.set()
            self.context.usage_tracker.record_tts(len(sentence.audio) / self._carrier_bytes_per_second, characters=len(sentence.text))
            tts_cache.put(self._tts_cache_key(sentence, language), bytes(sentence.audio))
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
            fallback = self.registry.get_tts(TTS_FALLBACK_PROVIDER)
            native = self._native_rate_kwargs(fallback)
            async with _speech_provider_slot():
                async for chunk in fallback.synthesize_stream(
                    text=sentence.text, voice_id=None, speed=spec.voice.speed,
                    language=sentence.language or self._sentence_language(sentence.text), **native,
                ):
                    if chunk:
                        sentence.audio.extend(self._carrier_audio(chunk, bool(native)))
                        sentence.updated.set()
            logger.warning(f"Spoke a sentence with the {TTS_FALLBACK_PROVIDER} voice after {spec.providers.tts} failed.")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Fallback TTS failed too: {type(e).__name__}: {e}")

    async def _play_sentence(self, turn: _AssistantTurn, sentence: _SpokenSentence, on_wait=None) -> None:
        """Sends one utterance's audio paced to real time; after a false interruption, resumes at the phrase it was in."""
        frame_bytes = self.telephony_provider.outbound_frame_bytes or 3200
        pos = 0
        resuming = False
        while True:
            if on_wait:
                on_wait()  # newly arrived sentences may now be within the prefetch window
            if self._paused:
                paused_at = self._pause_time
                await self._resume_event.wait()
                # The carrier buffer was flushed: pick up from the phrase the caller was hearing (a whole
                # reply is one utterance with streamed voices, so starting over would repeat all of it)
                pos = self._resume_position(sentence, paused_at)
                resuming = True
                continue

            # Don't start (or resume) talking over a caller who is mid-sentence
            if (pos == 0 or resuming) and self._caller_talking():
                await asyncio.sleep(0.05)
                continue
            if resuming:
                resuming = False
                if sentence.play_start is not None:
                    # Keep play_start where this utterance would have started, for what-was-heard estimates
                    sentence.play_start = max(time.monotonic(), self._play_clock) - pos / self._carrier_bytes_per_second

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

    def _resume_position(self, sentence: _SpokenSentence, paused_at: Optional[float]) -> int:
        """Where in an utterance to carry on after a false interruption: the start of the phrase then playing."""
        if sentence.play_start is None or paused_at is None:
            return 0
        heard = int((paused_at - sentence.play_start) * self._carrier_bytes_per_second)
        heard = max(0, min(heard, len(sentence.audio)))
        return phrase_start(bytes(sentence.audio[:heard]), heard, self._carrier_rate)

    async def _send_frame(self, turn: _AssistantTurn, sentence: _SpokenSentence, frame: bytes) -> None:
        now = time.monotonic()
        frame_ms = len(frame) / self._carrier_bytes_per_second * 1000.0
        start = max(now, self._play_clock)
        if sentence.play_start is None:
            sentence.play_start = start
            self._on_sentence_playing(turn, sentence)
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

        await self._send_carrier_audio(frame)
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
        limits = resolve_call_limits(self.context.agent_spec if self.context else None)
        cap = (self.call_record.metadata_ or {}).get("max_duration_s")  # e.g. short number test calls
        if cap:
            limits = replace(limits, max_call_duration_s=min(limits.max_call_duration_s or cap, cap))
        return limits

    def _budget_state(self) -> Optional[str]:
        """
        "over" once the call has spent its credit budget, "near" when it soon would (time to say goodbye),
        else None. Calls without a budget (tests, billing off) are never limited.
        """
        budget = (self.call_record.metadata_ or {}).get("credit_budget")
        if budget is None or not self.context:
            return None
        if self._budget_pricing is None:
            from app.services.pricing import get_pricing
            self._budget_pricing = get_pricing(self.db)
        elapsed = time.perf_counter() - self.t_call_start
        usage = self.context.usage_tracker.get_summary()
        spent = estimate_call_cost(elapsed, usage, self._budget_pricing)["charge_total"]
        if spent >= budget:
            return "over"
        ahead = estimate_call_cost(elapsed + BUDGET_LOOKAHEAD_S, usage, self._budget_pricing)["charge_total"]
        if ahead + max(1.0, budget * BUDGET_CUSHION_SHARE) >= budget:
            return "near"
        return None

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
            await self._disconnect_carrier()
        except Exception:
            pass

    def _on_sentence_playing(self, turn: _AssistantTurn, sentence: _SpokenSentence) -> None:
        """A sentence (or filler) started playing to the caller. Transports that show live text override this."""

    def _on_sentence_text(self, turn: _AssistantTurn, sentence: _SpokenSentence, text: str) -> None:
        """More text joined an utterance that is already playing. Transports that show live text override this."""

    # Carrier transport: the media-stream WebSocket. Browser test calls override these.

    async def _send_carrier_audio(self, frame: bytes) -> None:
        await self.websocket.send_text(self.telephony_provider.build_media_message(self.stream_sid, frame))

    async def _clear_carrier_playback(self) -> None:
        await self.websocket.send_text(self.telephony_provider.build_clear_message(self.stream_sid))

    async def _disconnect_carrier(self) -> None:
        await self.websocket.close()

    def _say_then_hang_up(self, text: str, reason: str) -> None:
        self._end_call_requested = True
        self._end_reason = reason
        self._start_turn(self._speak_text(text))

    async def _watchdog(self) -> None:
        """Handles caller silence, the maximum call length and the call's credit budget."""
        try:
            while not self.closed:
                await asyncio.sleep(0.5)
                if not self.context:
                    continue
                budget_state = self._budget_state()
                if budget_state == "over" and self._end_reason != "credit_budget_exhausted":
                    # Even mid-sentence: the client's credits are spent
                    logger.warning(f"Call {self.call_record.id} spent its credit budget; hanging up.")
                    self._end_call_requested = True
                    self._end_reason = "credit_budget_exhausted"
                    try:
                        await self._disconnect_carrier()
                    except Exception:
                        pass
                    continue
                if self._end_call_requested:
                    continue
                if not self._is_idle():
                    continue
                if budget_state == "near":
                    logger.info(f"Call {self.call_record.id} is near its credit budget; wrapping up.")
                    self._say_then_hang_up(self._farewell(), "credit_budget")
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
            total_s = (len(sentence.audio) / self._carrier_bytes_per_second) if sentence.done and sentence.audio else len(sentence.text) / CHARS_PER_SECOND
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
