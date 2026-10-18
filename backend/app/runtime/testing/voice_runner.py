"""
Voice test runs: a scripted caller talks to an AI Employee through the real call engine
(TelephonyMediaSession, the same one phone and browser calls use), and every turn is timed.

The caller's lines are audio, sent in real time in 20 ms frames, with silence (and optional line noise)
in between, exactly as a phone line delivers them. The engine decides when the caller has finished,
transcribes them, streams the reply into speech and handles interruptions as on a real call.

Scenario turns (TestScenario.turns_json) are strings or objects:
  "I'm looking for a 2BHK"                              a normal caller line
  {"text": "...", "pause_before_s": 1.0}                wait longer before saying it
  {"text": "wait, one question", "behavior": "interrupt", "after_s": 1.5}
                                                        cut in 1.5 s into the agent's reply to the previous line
  {"text": "haan", "behavior": "backchannel", "after_s": 1.0}
                                                        a short "mm-hmm" mid-reply: the agent should keep talking
  {"behavior": "silence", "seconds": 8}                 say nothing for 8 s (does the agent check in?)
  {"behavior": "hangup"}                                the caller hangs up

Line conditions (TestScenario.provider_config_json["voice"]):
  {"noise": "white|hum|babble", "noise_level": 0.05, "phone_line": true,
   "language": "en-IN", "caller_voice": "priya"}

Modes:
  mock   free: a synthetic caller voice, a speech-to-text that knows each line, a scripted LLM and a tone
         for the agent's voice. Checks the conversation flow, turn-taking and interruptions.
  real   the agent's own providers (Sarvam / Cartesia / Gemini) and a Sarvam caller voice. Gives the
         true timings a caller experiences. Costs about as much as a short call (never billed to the client).
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundException, ValidationException
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.runtime_session import RuntimeSession
from app.models.test_scenario import TestRun, TestRunEvent, TestScenario
from app.repositories.runtime_event_repository import RuntimeEventRepository
from app.runtime.context import TEST_CALL_PHONE
from app.runtime.events.types import RuntimeEventType
from app.runtime.providers.base import AudioResult, TranscriptResult
from app.runtime.providers.registry import ProviderRegistry, default_registry
from app.runtime.providers.stt import STTProvider
from app.runtime.providers.telephony.browser import BrowserTelephonyProvider
from app.runtime.providers.tts import TTSProvider
from app.runtime.runtime import AgentRuntime
from app.runtime.telephony.session import TelephonyMediaSession
from app.runtime.testing import caller_audio
from app.runtime.testing.business_state import MockBusinessState
from app.runtime.testing.caller_audio import FRAME_BYTES, FRAME_MS, SAMPLE_RATE, LineNoise
from app.runtime.testing.evaluation_engine import EvaluationEngine
from app.runtime.testing.mock_providers import TestingLLMAdapter, create_testing_tool_executor

logger = logging.getLogger("choranta.testing.voice")

BEHAVIORS = ("normal", "interrupt", "backchannel", "silence", "hangup")
DEFAULT_PAUSE_BEFORE_S = 0.3     # a person's pause between hearing the agent finish and replying
RESPONSE_TIMEOUT_S = 12.0        # no agent audio this long after the caller finished: the turn went unanswered
REPLY_TIMEOUT_S = 60.0           # an agent reply still playing after this long is cut off by the run
GREETING_TIMEOUT_S = 20.0

# Voice runs in progress on this server (each holds real-time audio and, in real mode, provider connections)
MAX_CONCURRENT_VOICE_RUNS = 3
active_voice_runs: set = set()


# ---------------------------------------------------------------------------
# Mock providers (free, offline)
# ---------------------------------------------------------------------------

class VoiceMockSTT(STTProvider):
    """Speech-to-text for mock runs: returns the caller line currently being said."""

    def __init__(self):
        self.current_line = ""

    @property
    def provider_name(self) -> str:
        return "voice_mock_stt"

    @property
    def environment(self) -> str:
        return "test"

    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass

    def start_stream(self) -> None:
        pass

    def end_stream(self) -> TranscriptResult:
        return TranscriptResult(text=self.current_line, is_final=True, confidence=1.0)

    def process_audio(self, audio_data: Any) -> TranscriptResult:
        return TranscriptResult(text=self.current_line, is_final=True, confidence=1.0)

    async def process_audio_async(self, audio_data: Any) -> TranscriptResult:
        await asyncio.sleep(0.05)
        return TranscriptResult(text=self.current_line, is_final=True, confidence=1.0)


class VoiceMockTTS(TTSProvider):
    """Text-to-speech for mock runs: a soft tone as long as the sentence would take to say."""

    @property
    def provider_name(self) -> str:
        return "voice_mock_tts"

    @property
    def environment(self) -> str:
        return "test"

    def initialize(self, config: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass

    def synthesize(self, text: str, voice_id: Optional[str] = None, speed: float = 1.0, pitch: float = 0.0,
                   emotion: Optional[str] = None, language: Optional[str] = None) -> AudioResult:
        duration = max(0.4, len(text) / 15.0 / max(speed or 1.0, 0.5))
        t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
        tone = (np.sin(2 * np.pi * 220 * t) * 2500).astype(np.int16).tobytes()
        return AudioResult(audio_bytes=tone, format="pcm_s16le", duration_seconds=round(duration, 2))


def _mock_registry(stt: VoiceMockSTT, llm_config: Dict[str, Any]) -> ProviderRegistry:
    registry = ProviderRegistry("mock")
    llm = TestingLLMAdapter("voice_test_llm")
    if llm_config:
        llm.configure(llm_config)
    tts = VoiceMockTTS()
    for name in ("cartesia", "sarvam", "gemini", "mock_stt", "mock_llm", "mock_tts"):
        registry.register_stt(name, stt)
        registry.register_llm(name, llm)
        registry.register_tts(name, tts)
    return registry


# ---------------------------------------------------------------------------
# The call: the engine with this run as its carrier
# ---------------------------------------------------------------------------

class VoiceTestCarrier(BrowserTelephonyProvider):
    """The test's 'phone line': 16kHz like a browser call, or 8kHz like a real phone line."""

    def __init__(self, sample_rate: int = 16000):
        self.carrier_sample_rate = sample_rate
        self.outbound_frame_bytes = sample_rate // 10 * 2

    @property
    def provider_name(self) -> str:
        return "voice_test"

    def normalize_audio_inbound(self, audio_chunk: bytes) -> bytes:
        if self.carrier_sample_rate == SAMPLE_RATE:
            return super().normalize_audio_inbound(audio_chunk)
        import audioop
        return audioop.ratecv(audio_chunk[: len(audio_chunk) // 2 * 2], 2, 1, self.carrier_sample_rate, SAMPLE_RATE, None)[0]

    def normalize_audio_outbound(self, pcm_bytes: bytes) -> bytes:
        if self.carrier_sample_rate == SAMPLE_RATE:
            return super().normalize_audio_outbound(pcm_bytes)
        import audioop
        return audioop.ratecv(pcm_bytes[: len(pcm_bytes) // 2 * 2], 2, 1, SAMPLE_RATE, self.carrier_sample_rate, None)[0]

    def to_carrier(self, pcm16k: bytes) -> bytes:
        return self.normalize_audio_outbound(pcm16k) if self.carrier_sample_rate != SAMPLE_RATE else pcm16k


class CallObserver:
    """What the caller experiences on the call, with timestamps (time.monotonic)."""

    def __init__(self):
        self.turn_index = -1                         # caller line being handled (-1: the greeting)
        self.agent_frames: List[float] = []          # arrival time of each agent audio frame
        self.cleared_at: List[float] = []            # the agent's audio was cut off (an interruption)
        self.hung_up_at: Optional[float] = None      # the agent ended the call
        self.transcripts: Dict[int, List[str]] = {}  # caller words the agent heard, by turn
        self.replies: Dict[int, List[Dict[str, Any]]] = {}
        self.latency: Dict[int, Dict[str, Any]] = {}  # stage timings of the first reply after each line
        self.tools: Dict[int, List[str]] = {}
        self.caller_speaking = False
        self.caller_line_is_interrupt = False
        self.talk_over_ms: Dict[int, float] = {}     # agent audio sent while the caller was mid-line, by turn

    def agent_audio(self, frame_ms: float) -> None:
        now = time.monotonic()
        self.agent_frames.append(now)
        if self.caller_speaking and not self.caller_line_is_interrupt:
            self.talk_over_ms[self.turn_index] = self.talk_over_ms.get(self.turn_index, 0.0) + frame_ms

    def first_agent_audio_after(self, t: float) -> Optional[float]:
        for ts in self.agent_frames:
            if ts >= t:
                return ts
        return None


class VoiceTestSession(TelephonyMediaSession):
    """A call whose carrier is the voice test run instead of a phone network."""

    def __init__(self, observer: CallObserver, call_record: Call, db: Session, carrier: VoiceTestCarrier,
                 runtime: AgentRuntime, registry: ProviderRegistry):
        super().__init__(websocket=None, call_record=call_record, stream_sid=call_record.provider_call_id,
                         db=db, telephony_provider=carrier, runtime=runtime, registry=registry)
        self.observer = observer
        # Caller line each agent reply answers (replies can end after the caller has moved on, e.g. when cut off)
        self._reply_owner: Dict[int, int] = {}

    def _start_turn(self, coro) -> None:
        super()._start_turn(coro)
        self._reply_owner[id(self._turn)] = self.observer.turn_index

    def _owner(self, turn=None) -> int:
        turn = turn if turn is not None else self._turn
        return self._reply_owner.get(id(turn), self.observer.turn_index) if turn is not None else self.observer.turn_index

    def _commit_turn(self, turn, interrupted: bool) -> None:
        self._committing = turn
        try:
            super()._commit_turn(turn, interrupted)
        finally:
            self._committing = None

    async def _send_carrier_audio(self, frame: bytes) -> None:
        self.observer.agent_audio(len(frame) / self._carrier_bytes_per_second * 1000.0)

    async def _clear_carrier_playback(self) -> None:
        self.observer.cleared_at.append(time.monotonic())

    async def _disconnect_carrier(self) -> None:
        self.observer.hung_up_at = time.monotonic()

    def _emit(self, event_type: RuntimeEventType, payload: Dict[str, Any]) -> None:
        super()._emit(event_type, payload)
        o = self.observer
        if event_type == RuntimeEventType.USER_TRANSCRIPT_FINAL:
            o.transcripts.setdefault(o.turn_index, []).append(payload.get("text", ""))
        elif event_type == RuntimeEventType.ASSISTANT_RESPONSE:
            o.replies.setdefault(self._owner(getattr(self, "_committing", None)), []).append(
                {"text": payload.get("text", ""), "interrupted": bool(payload.get("interrupted"))}
            )
        elif event_type == RuntimeEventType.TTS_STARTED and "response_latency_ms" in payload:
            o.latency.setdefault(self._owner(), {
                "engine_ms": payload.get("response_latency_ms"),
                "stt_ms": payload.get("stt_ms"),
                "llm_first_token_ms": payload.get("llm_first_token_ms"),
                "filler": payload.get("first_audio_filler"),
            })
        elif event_type == RuntimeEventType.TOOL_CALL_STARTED:
            o.tools.setdefault(self._owner(), []).append(payload.get("tool_name"))

    def agent_idle(self) -> bool:
        """The agent isn't replying and nothing it said is still playing."""
        replying = self._turn_task is not None and not self._turn_task.done()
        return not replying and not self._processing_utterance and time.monotonic() >= self._play_clock


# ---------------------------------------------------------------------------
# The caller
# ---------------------------------------------------------------------------

class CallerLine:
    """Feeds the caller's side of the line to the call in real time: speech when there is some, else silence."""

    def __init__(self, session: VoiceTestSession, carrier: VoiceTestCarrier, observer: CallObserver,
                 noise: Optional[LineNoise], phone_line: bool):
        self.session = session
        self.carrier = carrier
        self.observer = observer
        self.noise = noise
        self.phone_line = phone_line
        self._speech: List[bytes] = []
        self._speech_done: Optional[asyncio.Event] = None
        self.speech_started_at: Optional[float] = None
        self.speech_ended_at: Optional[float] = None
        self._task: Optional[asyncio.Task] = None
        self.stopped = False
        # Longest the call engine kept the line waiting (it blocked the event loop): on a phone line the
        # caller's audio would pile up the same way
        self.max_lag_ms = 0.0
        self.lag_by_turn: Dict[int, float] = {}

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        self.stopped = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def say(self, pcm16k: bytes, interrupting: bool = False) -> None:
        """Says `pcm16k` and returns once the last of it has gone down the line."""
        if self.phone_line:
            pcm16k = caller_audio.phone_line(pcm16k)
        frames = [pcm16k[i:i + FRAME_BYTES] for i in range(0, len(pcm16k), FRAME_BYTES)]
        if frames and len(frames[-1]) < FRAME_BYTES:
            frames[-1] = frames[-1] + b"\0" * (FRAME_BYTES - len(frames[-1]))
        self._speech_done = asyncio.Event()
        self.observer.caller_line_is_interrupt = interrupting
        self.speech_started_at = None
        self._speech = frames
        await self._speech_done.wait()

    async def _pump(self) -> None:
        silence = b"\0" * FRAME_BYTES
        next_at = time.monotonic()
        while not self.stopped and not self.session.closed:
            # Times are on the caller's own timeline (when each frame was due), not when it got through
            lag = (time.monotonic() - next_at) * 1000.0
            self.max_lag_ms = max(self.max_lag_ms, lag)
            turn = self.observer.turn_index
            self.lag_by_turn[turn] = max(self.lag_by_turn.get(turn, 0.0), lag)
            if self._speech:
                frame = self._speech.pop(0)
                if self.speech_started_at is None:
                    self.speech_started_at = next_at
                    self.observer.caller_speaking = True
                last = not self._speech
            else:
                frame, last = silence, False
            if self.noise is not None:
                frame = self.noise.mix(frame)
            try:
                await self.session.handle_carrier_audio(self.carrier.to_carrier(frame))
            except Exception as e:
                logger.error(f"Call engine failed on caller audio: {type(e).__name__}: {e}")
            if last:
                self.speech_ended_at = next_at + FRAME_MS / 1000.0
                self.observer.caller_speaking = False
                if self._speech_done:
                    self._speech_done.set()
            next_at += FRAME_MS / 1000.0
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))


def normalize_turns(raw_turns: List[Any]) -> List[Dict[str, Any]]:
    """Scenario turns as dicts with a known behavior (see the module docstring)."""
    turns = []
    for i, raw in enumerate(raw_turns or []):
        turn = {"text": raw} if isinstance(raw, str) else dict(raw or {})
        behavior = str(turn.get("behavior") or "normal").lower()
        if behavior not in BEHAVIORS:
            raise ValidationException(f"Turn {i + 1}: unknown behavior '{behavior}' (use {', '.join(BEHAVIORS)}).")
        turn["behavior"] = behavior
        turn["text"] = str(turn.get("text") or "").strip()
        if behavior in ("normal", "interrupt", "backchannel") and not turn["text"]:
            raise ValidationException(f"Turn {i + 1}: a '{behavior}' turn needs text for the caller to say.")
        turns.append(turn)
    return turns


def transcript_accuracy(expected: str, heard: str) -> float:
    """1 - word error rate between what the caller said and what the agent heard (0..1)."""
    def words(s: str) -> List[str]:
        return re.sub(r"[^\w\s]", " ", s.lower()).split()
    ref, hyp = words(expected), words(heard)
    if not ref:
        return 1.0 if not hyp else 0.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return round(max(0.0, 1.0 - prev[-1] / len(ref)), 3)


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

class VoiceScenarioRunner:
    """Runs a TestScenario as a voice call and records a TestRun (channel 'voice')."""

    def __init__(self, db: Session):
        self.db = db

    def create_run(self, scenario: TestScenario, provider_mode: str = "mock") -> TestRun:
        if provider_mode not in ("mock", "real"):
            raise ValidationException("Voice runs use provider mode 'mock' or 'real'.")
        if provider_mode == "real" and settings.RUNTIME_MODE != "real":
            raise ValidationException("Real voice runs need the server in RUNTIME_MODE=real.")
        normalize_turns(scenario.turns_json)
        agent = self.db.get(Agent, scenario.agent_id)
        version = self.db.get(AgentVersion, scenario.agent_version_id)
        if not agent:
            raise NotFoundException("Agent", scenario.agent_id)
        if not version:
            raise NotFoundException("AgentVersion", scenario.agent_version_id)
        if version.status != "PUBLISHED":
            raise ValidationException("Test scenario requires a published immutable agent version.")

        run = TestRun(
            id=generate_unique_id("run_"),
            scenario_id=scenario.id,
            client_id=agent.client_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            status="RUNNING",
            provider_mode=provider_mode,
            scenario_version=scenario.version_number,
            started_at=datetime.now(timezone.utc),
            turn_count=0,
            summary_json={},
            usage_json={},
            final_state_json={},
            metrics_json={"channel": "voice"},
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    async def run(self, scenario: TestScenario, provider_mode: str = "mock") -> TestRun:
        run = self.create_run(scenario, provider_mode)
        return await self.execute(run.id)

    async def execute(self, run_id: str) -> TestRun:
        run = self.db.get(TestRun, run_id)
        scenario = self.db.get(TestScenario, run.scenario_id)
        active_voice_runs.add(run_id)
        try:
            return await self._execute(run, scenario)
        finally:
            active_voice_runs.discard(run_id)

    async def _execute(self, run: TestRun, scenario: TestScenario) -> TestRun:
        started = time.monotonic()
        voice_cfg = (scenario.provider_config_json or {}).get("voice") or {}
        turns_spec = normalize_turns(scenario.turns_json)[: scenario.max_turns or 10]
        business_state = MockBusinessState.from_dict(scenario.initial_mock_state_json or {})
        observer = CallObserver()
        session: Optional[VoiceTestSession] = None
        line: Optional[CallerLine] = None
        runtime_session = None
        runtime_error: Optional[str] = None
        results: List[Dict[str, Any]] = []
        stt = VoiceMockSTT()

        try:
            if run.provider_mode == "real":
                registry = default_registry
            else:
                registry = _mock_registry(stt, (scenario.provider_config_json or {}).get("llm") or {})
            runtime = AgentRuntime(self.db, registry=registry, tool_executor=create_testing_tool_executor(business_state))
            runtime_session = runtime.start_session(
                agent_id=run.agent_id,
                agent_version_id=run.agent_version_id,
                metadata={"test_run_id": run.id, "scenario_id": scenario.id, "provider_mode": run.provider_mode,
                          "is_test": True, "channel": "voice_test"},
            )
            run.runtime_session_id = runtime_session.id
            self.db.commit()

            spec = runtime._contexts[runtime_session.id].agent_spec
            language = voice_cfg.get("language") or spec.languages.primary or "en-IN"
            caller_voice = voice_cfg.get("caller_voice") or _caller_voice(spec.voice.voice_id)
            call = self._create_call(run, runtime_session)
            carrier = VoiceTestCarrier(8000 if voice_cfg.get("phone_line") else SAMPLE_RATE)
            noise = LineNoise(voice_cfg["noise"], float(voice_cfg.get("noise_level", 0.05))) if voice_cfg.get("noise") else None

            # Caller audio is prepared up front so the call isn't kept waiting on speech synthesis
            audio: Dict[int, bytes] = {}
            for i, turn in enumerate(turns_spec):
                if turn["text"]:
                    audio[i] = (await caller_audio.spoken_line(turn["text"], language, caller_voice)
                                if run.provider_mode == "real" else caller_audio.synthetic_voice(turn["text"], seed=i))

            session = VoiceTestSession(observer, call, self.db, carrier, runtime, registry)
            await session.initialize()
            line = CallerLine(session, carrier, observer, noise, bool(voice_cfg.get("phone_line")))
            line.start()

            # The greeting (if any) plays first
            if session._turn_task is not None:
                await self._wait_until(lambda: session.agent_idle(), GREETING_TIMEOUT_S)

            for i, turn in enumerate(turns_spec):
                if session.closed or observer.hung_up_at is not None:
                    break
                if await self._cancelled(run.id):
                    break
                next_turn = turns_spec[i + 1] if i + 1 < len(turns_spec) else None
                observer.turn_index = i
                stt.current_line = turn["text"]
                result = await self._caller_turn(session, line, observer, turn, next_turn, audio.get(i, b""))
                results.append(result)
                if turn["behavior"] == "hangup":
                    break

            # Let the agent's last words finish (and a goodbye-and-hang-up complete)
            await self._wait_until(lambda: session.agent_idle() or observer.hung_up_at is not None, 15.0)
            if observer.hung_up_at is None:
                await asyncio.sleep(0.5)

        except Exception as exc:
            logger.error(f"Voice test run {run.id} failed: {exc}", exc_info=True)
            runtime_error = f"{type(exc).__name__}: {exc}"
        finally:
            if line:
                await line.stop()
            if session:
                try:
                    await session.close(reason="agent_ended" if observer.hung_up_at else "caller_hangup")
                except Exception as e:
                    logger.error(f"Closing voice test call failed: {type(e).__name__}: {e}")

        return self._finish(run, scenario, session, line, runtime_session, observer, results, business_state,
                            runtime_error, round((time.monotonic() - started) * 1000))

    async def _caller_turn(self, session: VoiceTestSession, line: CallerLine, observer: CallObserver,
                           turn: Dict[str, Any], next_turn: Optional[Dict[str, Any]], pcm: bytes) -> Dict[str, Any]:
        behavior = turn["behavior"]
        result: Dict[str, Any] = {"caller": turn["text"], "behavior": behavior}

        if behavior == "hangup":
            await session.close(reason="caller_hangup")
            return result

        if behavior == "silence":
            seconds = float(turn.get("seconds", 8))
            t0 = time.monotonic()
            await asyncio.sleep(seconds)
            reprompt = observer.first_agent_audio_after(t0)
            result["agent_spoke_during_silence_after_ms"] = round((reprompt - t0) * 1000) if reprompt else None
            await self._wait_until(lambda: session.agent_idle(), REPLY_TIMEOUT_S)
            return result

        if behavior in ("interrupt", "backchannel"):
            # The previous reply is already playing (see the end of this method)
            cleared_before = len(observer.cleared_at)
            result["agent_was_speaking"] = not session.agent_idle()
            await line.say(pcm, interrupting=True)
            t_cut_in = line.speech_started_at or time.monotonic()
            if behavior == "interrupt":
                cleared = [t for t in observer.cleared_at[cleared_before:] if t >= t_cut_in]
                result["interrupt_stop_ms"] = round((cleared[0] - t_cut_in) * 1000) if cleared else None
            else:
                # A backchannel shouldn't stop the reply; let it finish, then check how it ended
                await self._wait_until(lambda: session.agent_idle(), REPLY_TIMEOUT_S)
                prior = observer.replies.get(observer.turn_index - 1) or []
                result["agent_kept_talking"] = not (prior and prior[-1]["interrupted"])
                result["heard"] = " ".join(observer.transcripts.get(observer.turn_index, []))
                return result
        else:
            await asyncio.sleep(float(turn.get("pause_before_s", DEFAULT_PAUSE_BEFORE_S)))
            await line.say(pcm)

        # Wait for the agent to answer: the gap is from the caller's last word to the agent's first sound
        t_said = line.speech_ended_at or time.monotonic()
        await self._wait_until(lambda: observer.first_agent_audio_after(t_said) is not None
                               or observer.hung_up_at is not None, RESPONSE_TIMEOUT_S)
        first = observer.first_agent_audio_after(t_said)
        result["response_gap_ms"] = round((first - t_said) * 1000) if first else None

        if next_turn and next_turn["behavior"] in ("interrupt", "backchannel") and first:
            # The next line cuts into this reply part-way through
            await asyncio.sleep(max(0.0, first + float(next_turn.get("after_s", 1.5)) - time.monotonic()))
        else:
            await self._wait_until(lambda: session.agent_idle(), REPLY_TIMEOUT_S)
        return result

    @staticmethod
    async def _wait_until(condition, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if condition():
                return True
            await asyncio.sleep(0.05)
        return condition()

    @staticmethod
    async def _cancelled(run_id: str) -> bool:
        """Whether the run was cancelled from the studio (checked off the event loop: the database may be remote)."""
        def check() -> bool:
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                status = db.query(TestRun.status).filter(TestRun.id == run_id).scalar()
                return status == "CANCELLED"
            finally:
                db.close()
        try:
            return await asyncio.to_thread(check)
        except Exception:
            return False

    def _create_call(self, run: TestRun, runtime_session) -> Call:
        version = self.db.get(AgentVersion, run.agent_version_id)
        business = ((version.configuration_json or {}).get("business_context") or {}) if version else {}
        outbound = str(business.get("call_direction") or "inbound").lower() == "outbound"
        caller, destination = ("voice_test", TEST_CALL_PHONE) if outbound else (TEST_CALL_PHONE, "voice_test")
        now = datetime.now(timezone.utc)
        call = Call(
            id=generate_unique_id("call", 12),
            client_id=run.client_id,
            agent_id=run.agent_id,
            agent_version_id=run.agent_version_id,
            runtime_session_id=runtime_session.id,
            provider="voice_test",
            provider_call_id=generate_unique_id("vtc", 16),
            direction="OUTBOUND" if outbound else "INBOUND",
            caller_number=caller,
            destination_number=destination,
            status="ANSWERED",
            started_at=now,
            answered_at=now,
            duration_seconds=0.0,
            metadata_={"is_test": True, "channel": "voice_test", "test_run_id": run.id},
        )
        self.db.add(call)
        self.db.commit()
        self.db.refresh(call)
        return call

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _finish(self, run: TestRun, scenario: TestScenario, session: Optional[VoiceTestSession],
                line: Optional[CallerLine], runtime_session,
                observer: CallObserver, results: List[Dict[str, Any]], business_state: MockBusinessState,
                runtime_error: Optional[str], duration_ms: int) -> TestRun:
        self.db.refresh(run)
        cancelled = run.status == "CANCELLED"

        turns: List[Dict[str, Any]] = []
        for i, r in enumerate(results):
            replies = observer.replies.get(i) or []
            heard = r.get("heard", " ".join(observer.transcripts.get(i, [])))
            latency = observer.latency.get(i) or {}
            turn = {
                "turn_number": i + 1,
                **r,
                "heard": heard,
                "assistant": " ".join(x["text"] for x in replies if x["text"]),
                "assistant_interrupted": any(x["interrupted"] for x in replies),
                "talk_over_ms": round(observer.talk_over_ms.get(i, 0.0)),
                "engine_stall_ms": round(line.lag_by_turn.get(i, 0.0)) if line else None,
                "tool_calls_executed": len(observer.tools.get(i, [])),
                "tools": observer.tools.get(i, []),
                "stage_latencies": {
                    "stt_ms": latency.get("stt_ms"),
                    "llm_first_token_ms": latency.get("llm_first_token_ms"),
                    "engine_ms": latency.get("engine_ms"),
                    "first_audio_filler": latency.get("filler"),
                },
            }
            if r["behavior"] in ("normal", "interrupt") and r["caller"]:
                turn["transcript_accuracy"] = transcript_accuracy(r["caller"], heard)
            turns.append(turn)

        gaps = [t["response_gap_ms"] for t in turns if t.get("response_gap_ms") is not None]
        answerable = [t for t in turns if t["behavior"] in ("normal", "interrupt")]
        accuracies = [t["transcript_accuracy"] for t in turns if "transcript_accuracy" in t]
        stops = [t.get("interrupt_stop_ms") for t in turns if t["behavior"] == "interrupt"]
        backchannels = [t["agent_kept_talking"] for t in turns if t["behavior"] == "backchannel"]
        call = session.call_record if session else None
        voice_metrics = {
            "channel": "voice",
            "provider_mode": run.provider_mode,
            "response_gaps_ms": gaps,
            "avg_response_gap_ms": round(sum(gaps) / len(gaps)) if gaps else None,
            "p50_response_gap_ms": sorted(gaps)[len(gaps) // 2] if gaps else None,
            "max_response_gap_ms": max(gaps) if gaps else None,
            "unanswered_turns": [t["turn_number"] for t in answerable if t.get("response_gap_ms") is None],
            "interrupt_stops_ms": stops,
            "backchannels_kept_talking": backchannels,
            "transcript_accuracy": round(sum(accuracies) / len(accuracies), 3) if accuracies else None,
            "talk_over_ms": round(sum(observer.talk_over_ms.values())),
            "max_engine_stall_ms": round(line.max_lag_ms) if line else None,
            "call_ended_by": "agent" if observer.hung_up_at else ("caller" if session else None),
            "end_reason": call.termination_reason if call else None,
            "call_id": call.id if call else None,
            "recording_file": (call.metadata_ or {}).get("recording_file") if call else None,
            "conversation_quality": session.conversation_quality() if session else {},
        }

        runtime_events = RuntimeEventRepository(self.db).list_by_session(runtime_session.id) if runtime_session else []
        session_status = "ERROR"
        if runtime_session:
            record = self.db.get(RuntimeSession, runtime_session.id)
            if record:
                self.db.refresh(record)
                session_status = record.status
                run.usage_json = record.usage_json or {}

        summary = EvaluationEngine().evaluate(
            expected=scenario.expected_json or {},
            turns=turns,
            events=runtime_events,
            business_state=business_state,
            max_turns=scenario.max_turns or 10,
            duration_ms=duration_ms,
            session_status=session_status,
            caller_goal=scenario.caller_goal or "",
            tenant_context={"client_id": scenario.client_id, "agent_client_id": run.client_id,
                            "scenario_client_id": scenario.client_id},
            runtime_error=runtime_error,
            voice_metrics=voice_metrics,
        )

        run.status = "CANCELLED" if cancelled else summary.overall_status
        run.ended_at = datetime.now(timezone.utc)
        run.duration_ms = duration_ms
        run.turn_count = len(turns)
        run.final_state_json = business_state.to_dict()
        run.metrics_json = {"total_duration_ms": duration_ms, "turn_count": len(turns),
                            "tool_calls_total": sum(t["tool_calls_executed"] for t in turns),
                            "is_simulated_latency": False, **voice_metrics}
        run.summary_json = {
            "assertions": [a.model_dump() for a in summary.assertions],
            "passed_count": summary.passed_count,
            "failed_count": summary.failed_count,
            "error_count": summary.error_count,
            "turns": turns,
            "greeting": " ".join(x["text"] for x in observer.replies.get(-1, []) if x["text"]),
            "error": runtime_error,
        }
        for event in runtime_events:
            self.db.add(TestRunEvent(
                id=generate_unique_id("runevt_"), run_id=run.id, session_id=runtime_session.id,
                event_type=event.event_type, timestamp=event.timestamp, metadata_json=event.payload_json or {},
            ))
        self.db.add(TestRunEvent(
            id=generate_unique_id("runevt_"), run_id=run.id,
            session_id=runtime_session.id if runtime_session else None,
            event_type="ASSERTIONS_EVALUATED", timestamp=datetime.now(timezone.utc),
            metadata_json={"overall_status": summary.overall_status, "passed_count": summary.passed_count,
                           "failed_count": summary.failed_count},
        ))
        self.db.commit()
        self.db.refresh(run)
        return run


def _caller_voice(agent_voice: Optional[str]) -> str:
    """A Sarvam voice for the caller that differs from the agent's, so the recording is easy to follow."""
    for voice in ("priya", "varun", "ishita", "mani"):
        if voice != agent_voice:
            return voice
    return "priya"
