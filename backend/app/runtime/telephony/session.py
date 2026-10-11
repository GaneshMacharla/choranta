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
from app.runtime.runtime import AgentRuntime, MAX_TOOL_ROUNDS
from app.runtime.providers.registry import default_registry
from app.runtime.providers.telephony import TelephonyProvider
from app.runtime.telephony.endpointing import SpeechEndpointer, EndpointerConfig
from app.runtime.telephony.speech_text import SentenceChunker, clean_for_speech, is_backchannel
from app.runtime.tools.catalog import describe_tools
from app.runtime.telephony.recorder import CallRecorder

logger = logging.getLogger("choranta.runtime.telephony.session")

active_telephony_calls: Set[str] = set()

# Audio already handed to the carrier but not yet played; small so interruptions are near-instant
PLAYBACK_LEAD_MS = 250
# Events are written to the database in the background at this interval (never on the audio path)
EVENT_FLUSH_INTERVAL_S = 0.5
# Speaking-rate estimate used to work out how much of a sentence the caller heard before cutting in
CHARS_PER_SECOND = 15.0
CALL_ENDPOINTER_CONFIG = EndpointerConfig(end_silence_ms=600)
# Appended to the agent's instructions on phone calls: short spoken replies are both more natural
# and cheaper (TTS is billed per character).
PHONE_STYLE_MARKER = "Live phone call style:"
PHONE_STYLE_INSTRUCTIONS = (
    "\n\n" + PHONE_STYLE_MARKER + "\n"
    "- You are speaking on a live phone call. Reply in one or two short sentences (under 30 words).\n"
    "- Ask only one question at a time. Never use lists, markdown, emojis, symbols or URLs.\n"
    "- Say numbers and amounts the way people speak them, e.g. 'seventy-five lakh rupees'.\n"
    "- When the conversation is complete or the caller wants to stop, say a brief goodbye and call the end_call tool."
)
END_CALL_TOOL = {
    "name": "end_call",
    "id": "end_call",
    "description": "Hang up the phone call. Use after saying goodbye, when the conversation is complete or the caller asks to end the call.",
    "input_schema": {"type": "object", "properties": {"reason": {"type": "string", "description": "Why the call is ending"}}},
}
DEFAULT_FAREWELL = "Thank you for your time. Have a great day!"
SILENCE_REPROMPT_TEXT = "Are you still there?"
SILENCE_GOODBYE_TEXT = "I'll let you go for now. Thank you, goodbye!"

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


class _SpokenSentence:
    """One sentence of a reply: its synthesized carrier audio and when it was played."""

    def __init__(self, text: str):
        self.text = text
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
        self.endpointer = SpeechEndpointer(CALL_ENDPOINTER_CONFIG)
        self._utterance_queue: "asyncio.Queue[bytes]" = asyncio.Queue()
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
            "call_id": self.call_record.id, "duration_seconds": self.call_record.duration_seconds
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
            elif event.kind == "utterance":
                logger.info(f"Caller utterance detected ({event.speech_ms:.0f} ms of speech).")
                await self.execute_turn(event.audio, t_end=time.perf_counter())

    async def execute_turn(self, pcm16_audio_bytes: bytes, t_start: Optional[float] = None, t_end: Optional[float] = None):
        """Queues one complete caller utterance; utterances are handled strictly in order."""
        if self.closed:
            return
        await self._utterance_queue.put((pcm16_audio_bytes, t_end or time.perf_counter()))

    async def _utterance_loop(self) -> None:
        while not self.closed:
            audio, t_end = await self._utterance_queue.get()
            try:
                await self._handle_utterance(audio, t_end)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error handling caller utterance: {type(e).__name__}: {e}")

    async def _handle_utterance(self, audio: bytes, t_end: float) -> None:
        if not self.context or not self.runtime_session:
            return
        self._processing_utterance = True
        try:
            await self._handle_utterance_inner(audio, t_end)
        finally:
            self._processing_utterance = False
            self._last_activity = time.monotonic()

    async def _handle_utterance_inner(self, audio: bytes, t_end: float) -> None:
        stt_provider = default_registry.get_stt(self.context.agent_spec.providers.stt)
        async with _speech_provider_slot():
            transcript = await stt_provider.process_audio_async(audio)
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
        self._start_turn(self._respond(t_end))

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
        self._paused = False
        self._pause_time = None
        self._resume_event.set()

    async def _interrupt_current_turn(self) -> None:
        task, turn = self._turn_task, self._turn
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
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
        max_chars = max(0, settings.VOICE_MAX_REPLY_CHARS)
        queued_chars = 0
        capped = False

        sentences: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        player = asyncio.create_task(self._play_sentences(turn, sentences))
        chunker = SentenceChunker()
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
                    system_instruction=self.context.conversation.system_instruction,
                    messages=messages,
                    available_tools=tools if rounds < MAX_TOOL_ROUNDS else None,
                )
                streamed_text: List[str] = []
                try:
                    async for item in stream:
                        if isinstance(item, str):
                            if first_token_ms is None:
                                first_token_ms = round((time.perf_counter() - t_llm) * 1000)
                            streamed_text.append(item)
                            turn.full_text_parts.append(item)
                            for sentence in chunker.feed(item):
                                await sentences.put(sentence)
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
                if final is None or not final.tool_calls or rounds >= MAX_TOOL_ROUNDS:
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
                        await sentences.put(sentence)
                        queued_chars += len(sentence)
                    if not queued_chars:
                        farewell = self._farewell()
                        turn.full_text_parts.append(farewell)
                        await sentences.put(farewell)
                    break

                # Tool round: speak any lead-in text first, then run the tools
                for sentence in chunker.flush():
                    await sentences.put(sentence)
                rounds += 1
                self.context.conversation.add_assistant_message(
                    content=final.text,
                    tool_calls=[tc.model_dump() for tc in final.tool_calls]
                )
                for tc in final.tool_calls:
                    self._emit(RuntimeEventType.TOOL_CALL_STARTED, {
                        "call_id": tc.id, "tool_name": tc.tool_name, "arguments": tc.arguments
                    })
                    result = await asyncio.to_thread(
                        self.runtime.tool_executor.execute_tool,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        enabled_tool_ids=self.context.active_tools
                    )
                    self._emit(RuntimeEventType.TOOL_CALL_COMPLETED, {
                        "call_id": tc.id, "success": result.success, "data": result.data, "error": result.error
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
                    await sentences.put(sentence)
            if not "".join(turn.full_text_parts).strip():
                fallback = self.context.agent_spec.conversation.fallback_response or "Sorry, could you say that again?"
                turn.full_text_parts.append(fallback)
                await sentences.put(fallback)
            self._emit(RuntimeEventType.LLM_RESPONSE, {"first_token_ms": first_token_ms, "tool_rounds": rounds})
            await sentences.put(None)
            await player
        finally:
            if not player.done():
                player.cancel()
                try:
                    await player
                except (asyncio.CancelledError, Exception):
                    pass

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
                text = clean_for_speech(text)
                if not text:
                    continue
                turn.sentences.append(_SpokenSentence(text))
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
        try:
            # Sentences queue for a provider slot in order, so the next one to play goes first
            async with _speech_provider_slot():
                async for chunk in tts.synthesize_stream(
                    text=sentence.text,
                    voice_id=self.context.agent_spec.voice.voice_id,
                    speed=self.context.agent_spec.voice.speed,
                    language=self.context.agent_spec.languages.primary
                ):
                    if chunk:
                        sentence.audio.extend(self.telephony_provider.normalize_audio_outbound(chunk))
                        sentence.updated.set()
            self.context.usage_tracker.record_tts(len(sentence.audio) / 16000.0, characters=len(sentence.text))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"TTS failed for sentence: {type(e).__name__}: {e}")
        finally:
            sentence.done = True
            sentence.updated.set()

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
        self._play_clock = start + frame_ms / 1000.0
        sentence.play_end = self._play_clock

        if not turn.started_audio:
            turn.started_audio = True
            if turn.t_reference:
                latency = round((time.perf_counter() - turn.t_reference) * 1000)
                logger.info(f"Agent started speaking {latency} ms after the caller finished.")
                self._emit(RuntimeEventType.TTS_STARTED, {"response_latency_ms": latency})
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
        conversation = self.context.conversation
        if PHONE_STYLE_MARKER in conversation.system_instruction:
            return
        conversation.system_instruction += PHONE_STYLE_INSTRUCTIONS
        if conversation.messages and conversation.messages[0].role == ConversationRole.SYSTEM:
            conversation.messages[0].content = conversation.system_instruction.strip()

    def _farewell(self) -> str:
        farewell = (self.context.agent_spec.conversation.farewell or "").strip() if self.context else ""
        return farewell or DEFAULT_FAREWELL

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
                elapsed = time.perf_counter() - self.t_call_start
                if settings.CALL_MAX_DURATION_S and elapsed >= settings.CALL_MAX_DURATION_S:
                    logger.info(f"Call {self.call_record.id} reached the maximum duration; wrapping up.")
                    self._say_then_hang_up(self._farewell(), "max_duration")
                    continue
                silent = time.monotonic() - self._last_activity
                if not self._reprompted and silent >= settings.CALL_SILENCE_REPROMPT_S:
                    self._reprompted = True
                    self._start_turn(self._speak_text(SILENCE_REPROMPT_TEXT))
                elif self._reprompted and silent >= settings.CALL_SILENCE_HANGUP_S:
                    logger.info(f"Caller silent on call {self.call_record.id}; hanging up.")
                    self._say_then_hang_up(SILENCE_GOODBYE_TEXT, "caller_silent")
        except asyncio.CancelledError:
            pass

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
        if not interrupted:
            return " ".join(s.text for s in turn.sentences) or "".join(turn.full_text_parts).strip()
        cutoff = self._pause_time or time.monotonic()
        heard: List[str] = []
        for sentence in turn.sentences:
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
