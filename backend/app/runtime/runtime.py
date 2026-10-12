import logging
from app.runtime.tools.catalog import describe_tools
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional
from sqlalchemy.orm import Session
from app.core.exceptions import NotFoundException, ValidationException
from app.core.security import generate_unique_id
from app.models.runtime_session import RuntimeSession
from app.repositories.runtime_session_repository import RuntimeSessionRepository
from app.schemas.agent_spec import CanonicalAgentSpec
from app.runtime.exceptions import (
    AgentVersionNotFound,
    AgentVersionNotPublished,
    InvalidSessionTransition,
    SessionNotActiveError,
    RuntimeInitializationError,
)
from app.runtime.lifecycle import SessionStatus, validate_session_transition
from app.runtime.context import RuntimeContext
from app.runtime.events.emitter import EventEmitter
from app.runtime.events.types import RuntimeEventType
from app.runtime.providers.registry import ProviderRegistry, default_registry
from app.runtime.tools.executor import ToolExecutor
from app.runtime.readiness.checker import RuntimeReadinessChecker
from app.runtime.call_limits import resolve_call_limits

logger = logging.getLogger("choranta.runtime")

# Active session contexts shared by every AgentRuntime instance in this process.
# API routes build a new AgentRuntime per request, so per-instance state would lose
# conversation history between turns and force a database rehydration every turn.
_ACTIVE_CONTEXTS: Dict[str, RuntimeContext] = {}

# Serializes deferred turn writes per session so the latest snapshot always wins.
_PERSIST_LOCKS: Dict[str, threading.Lock] = defaultdict(threading.Lock)


def _apply_turn_state(session_record: RuntimeSession, context: RuntimeContext) -> None:
    """Copies the running transcript and usage from a RuntimeContext onto its session record."""
    meta = dict(session_record.metadata_ or {})
    transcript_entries = [
        {"role": m.role.value, "content": m.content, "timestamp": m.timestamp.isoformat()}
        for m in context.conversation.messages
        if m.role.value in ("user", "assistant") and not m.tool_calls
    ]
    meta["transcript"] = transcript_entries
    meta["transcript_text"] = "\n".join([f"{t['role'].capitalize()}: {t['content']}" for t in transcript_entries])
    session_record.metadata_ = meta
    session_record.usage_json = context.usage_tracker.get_summary()


def persist_turn(bind: Any, session_id: str, context: RuntimeContext, event_records: List[Any]) -> None:
    """
    Writes a turn's buffered events and the session's latest transcript/usage in a single
    transaction. Runs after the response has been sent (FastAPI background task).
    """
    with _PERSIST_LOCKS[session_id]:
        db = Session(bind=bind)
        try:
            for record in event_records:
                db.add(record)
            session_record = db.get(RuntimeSession, session_id)
            if session_record:
                _apply_turn_state(session_record, context)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to persist turn for session {session_id}: {type(e).__name__}: {e}")
        finally:
            db.close()


class AgentRuntime:
    """
    Choranta Voice Runtime Orchestration Engine.
    Executes immutable published AgentVersion specifications through provider-independent abstractions.
    """

    def __init__(self, db: Session, registry: ProviderRegistry = default_registry, tool_executor: Optional[ToolExecutor] = None):
        self.db = db
        self.registry = registry
        self.session_repo = RuntimeSessionRepository(db)
        self.emitter = EventEmitter(db)
        self.tool_executor = tool_executor or ToolExecutor()
        self.readiness_checker = RuntimeReadinessChecker(db, registry)

        # In-memory active session contexts: session_id -> RuntimeContext
        self._contexts: Dict[str, RuntimeContext] = _ACTIVE_CONTEXTS

    def start_session(
        self,
        agent_id: str,
        agent_version_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RuntimeSession:
        """
        Loads an immutable AgentVersion, verifies readiness, and initiates an active runtime session.
        """
        # 1. Readiness verification
        readiness = self.readiness_checker.check(agent_id, agent_version_id)
        if not readiness["ready"]:
            error_msg = "; ".join(readiness["errors"])
            raise ValidationException(f"Runtime readiness check failed: {error_msg}", details=readiness)

        # 2. Retrieve version record and client ID
        from app.models.agent_version import AgentVersion
        from app.models.agent import Agent

        # Primary-key gets reuse the rows the readiness check just loaded (no extra round-trips)
        version = self.db.get(AgentVersion, agent_version_id)
        if not version:
            raise AgentVersionNotFound(agent_version_id)
        if version.status != "PUBLISHED":
            raise AgentVersionNotPublished(agent_version_id, version.status)

        agent = self.db.get(Agent, agent_id)
        if not agent:
            raise NotFoundException("Agent", agent_id)

        spec = CanonicalAgentSpec.model_validate(version.configuration_json)

        # 3. Retrieve or populate lead & company metadata (with mock fallback if no source)
        session_metadata = dict(metadata or {})
        from app.models.client import Client
        client = self.db.get(Client, agent.client_id)
        company_name = (
            session_metadata.get("company_name")
            or (spec.business_context.business_name if spec.business_context and spec.business_context.business_name else None)
            or (spec.identity.organization if spec.identity and spec.identity.organization else None)
            or (client.name if client and client.name and client.name != "Default Client" else None)
            or "Apex Realty Bangalore"
        )
        if str(company_name).strip().lower() in ("", "none", "null", "default client"):
            company_name = "Apex Realty Bangalore"
        session_metadata["company_name"] = str(company_name).strip()

        if not session_metadata.get("user_name") or str(session_metadata.get("user_name")).strip().lower() in ("", "none", "null", "there"):
            from app.models.lead import Lead
            lead = self.db.query(Lead).filter(Lead.client_id == agent.client_id).first()
            if not lead:
                lead = self.db.query(Lead).first()
            if lead and lead.name and str(lead.name).strip().lower() not in ("there", ""):
                session_metadata["user_name"] = lead.name
                session_metadata.setdefault("lead_id", lead.id)
                if hasattr(lead, "property_viewed") and lead.property_viewed:
                    session_metadata.setdefault("property_viewed", lead.property_viewed)
                if hasattr(lead, "enquiry_location") and lead.enquiry_location:
                    session_metadata.setdefault("enquiry_location", lead.enquiry_location)
                if hasattr(lead, "enquiry_budget") and lead.enquiry_budget:
                    session_metadata.setdefault("enquiry_budget", lead.enquiry_budget)
                if hasattr(lead, "enquiry_bhk") and lead.enquiry_bhk:
                    session_metadata.setdefault("enquiry_bhk", lead.enquiry_bhk)
            else:
                session_metadata["user_name"] = "Rahul Sharma"
                session_metadata.setdefault("lead_id", "lead_re_101")
                session_metadata.setdefault("property_viewed", "Prestige Highline Residences")
                session_metadata.setdefault("enquiry_location", "Whitefield")
                session_metadata.setdefault("enquiry_budget", "₹90 Lakhs - ₹1.1 Cr")
                session_metadata.setdefault("enquiry_bhk", "3 BHK")

        # 4. Build the session record. The lifecycle (CREATED -> INITIALIZING -> ACTIVE) runs in
        # memory and is saved with its events in a single commit: each commit is a database
        # round-trip, and a remote database makes per-step commits the dominant start-up cost.
        self.emitter.start_buffering()
        session_id = generate_unique_id("ses", 12)
        session_record = RuntimeSession(
            id=session_id,
            client_id=agent.client_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            status=SessionStatus.CREATED.value,
            metadata_=session_metadata,
            usage_json={},
            created_at=datetime.now(timezone.utc)
        )
        saved_session = session_record

        # Emit SESSION_CREATED
        self.emitter.emit(
            RuntimeEventType.SESSION_CREATED,
            session_id=session_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            client_id=agent.client_id,
            payload={"status": SessionStatus.CREATED.value, "metadata": session_metadata}
        )

        # 5. Transition to INITIALIZING
        validate_session_transition(saved_session.status, SessionStatus.INITIALIZING.value)
        saved_session.status = SessionStatus.INITIALIZING.value

        self.emitter.emit(
            RuntimeEventType.SESSION_INITIALIZING,
            session_id=session_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            client_id=agent.client_id
        )

        # 6. Initialize RuntimeContext and providers
        context = RuntimeContext(
            session_id=session_id,
            agent_id=agent_id,
            client_id=agent.client_id,
            agent_version_id=agent_version_id,
            agent_spec=spec,
            metadata=session_metadata
        )
        session_metadata["resolved_greeting"] = context.resolved_greeting
        saved_session.metadata_ = session_metadata

        # Initialize providers from registry
        stt_provider = self.registry.get_stt(spec.providers.stt)
        llm_provider = self.registry.get_llm(spec.providers.llm)
        tts_provider = self.registry.get_tts(spec.providers.tts)

        try:
            stt_provider.initialize({})
            llm_provider.initialize({})
            tts_provider.initialize({})
        except Exception:
            self.emitter.drain_buffer()
            raise

        # 6. Transition to ACTIVE
        validate_session_transition(saved_session.status, SessionStatus.ACTIVE.value)
        saved_session.status = SessionStatus.ACTIVE.value
        saved_session.started_at = datetime.now(timezone.utc)

        self.emitter.emit(
            RuntimeEventType.SESSION_STARTED,
            session_id=session_id,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            client_id=agent.client_id,
            payload={
                "started_at": saved_session.started_at.isoformat(),
                "greeting": context.resolved_greeting or spec.conversation.greeting
            }
        )

        self.db.add(saved_session)
        self.db.add_all(self.emitter.drain_buffer())
        # Keep attributes loaded after commit so the response needs no re-read
        expire_on_commit = self.db.expire_on_commit
        self.db.expire_on_commit = False
        try:
            self.db.commit()
        finally:
            self.db.expire_on_commit = expire_on_commit
        self._contexts[session_id] = context

        logger.info(f"RuntimeSession '{session_id}' started for agent '{agent_id}' (version: {version.version_number})")
        return saved_session

    def _load_context(self, session_record: RuntimeSession) -> RuntimeContext:
        """Rehydrates a RuntimeContext (including prior conversation turns) from the pinned AgentVersion."""
        from app.models.agent_version import AgentVersion
        version = self.db.query(AgentVersion).filter(AgentVersion.id == session_record.agent_version_id).first()
        if not version:
            raise AgentVersionNotFound(session_record.agent_version_id)
        spec = CanonicalAgentSpec.model_validate(version.configuration_json)
        context = RuntimeContext(
            session_id=session_record.id,
            agent_id=session_record.agent_id,
            client_id=session_record.client_id,
            agent_version_id=session_record.agent_version_id,
            agent_spec=spec,
            metadata=dict(session_record.metadata_ or {})
        )
        for entry in (session_record.metadata_ or {}).get("transcript") or []:
            if entry.get("role") == "user":
                context.conversation.add_user_message(entry.get("content") or "")
            elif entry.get("role") == "assistant":
                context.conversation.add_assistant_message(content=entry.get("content") or "")
        self._contexts[session_record.id] = context
        return context

    def _resolve_turn_context(self, session_id: str, require_record: bool):
        """
        Returns (context, session_record) for an ACTIVE session.
        Cached contexts only exist for ACTIVE sessions (they are dropped on end/fail), so when
        require_record is False and the context is cached the session lookup is skipped entirely.
        """
        context = self._contexts.get(session_id)
        session_record: Optional[RuntimeSession] = None

        if context is None or require_record:
            session_record = self.session_repo.get_by_id(session_id)
            if not session_record:
                raise NotFoundException("RuntimeSession", session_id)

            if session_record.status != SessionStatus.ACTIVE.value:
                self._contexts.pop(session_id, None)
                raise SessionNotActiveError(session_id, session_record.status)

            if context is None:
                context = self._load_context(session_record)

        return context, session_record

    def stream_turn(self, session_id: str, input_text: str) -> Iterator[Dict[str, Any]]:
        """
        Text chat turn with token streaming. Session validation runs eagerly (so errors surface
        before any output); the returned iterator then yields:
          {"type": "delta", "text": ...}            assistant text as the LLM produces it
          {"type": "tool", "status": "started"|"completed", "tool_name": ...}
          {"type": "done", "assistant_response", "transcript", "tool_calls_executed", "usage",
           "events", "persist"}                      final turn summary; "persist" writes the turn
        """
        context, _ = self._resolve_turn_context(session_id, require_record=False)
        return self._stream_turn_events(session_id, context, input_text)

    def _stream_turn_events(self, session_id: str, context: RuntimeContext, input_text: str) -> Iterator[Dict[str, Any]]:
        spec = context.agent_spec
        stt_p = self.registry.get_stt(spec.providers.stt)
        llm_p = self.registry.get_llm(spec.providers.llm)
        ids = {
            "session_id": session_id,
            "agent_id": context.agent_id,
            "agent_version_id": context.agent_version_id,
            "client_id": context.client_id,
        }

        self.emitter.start_buffering()
        streamed_parts: List[str] = []
        tool_calls_executed = 0
        try:
            self.emitter.emit(RuntimeEventType.USER_SPEECH_STARTED, **ids)
            stt_result = stt_p.process_audio(input_text)
            user_text = stt_result.text
            context.usage_tracker.record_stt(2.5)  # deterministic mock STT duration
            self.emitter.emit(
                RuntimeEventType.USER_TRANSCRIPT_FINAL, **ids,
                payload={"text": user_text, "confidence": stt_result.confidence}
            )
            context.conversation.add_user_message(user_text)

            available_tools_list = describe_tools(self.db, context.active_tools)

            def run_llm(tools):
                final = None
                for item in llm_p.generate_stream(
                    system_instruction=context.conversation.system_instruction,
                    messages=context.conversation.to_llm_messages(),
                    available_tools=tools
                ):
                    if isinstance(item, str):
                        streamed_parts.append(item)
                        yield {"type": "delta", "text": item}
                    else:
                        final = item
                context.usage_tracker.record_llm(
                    final.usage.get("input_tokens", 0),
                    final.usage.get("output_tokens", 0)
                )
                return final

            self.emitter.emit(RuntimeEventType.LLM_REQUEST_STARTED, **ids)
            llm_result = yield from run_llm(available_tools_list)
            self.emitter.emit(
                RuntimeEventType.LLM_RESPONSE, **ids,
                payload={"has_tool_calls": len(llm_result.tool_calls) > 0, "finish_reason": llm_result.finish_reason}
            )

            tool_rounds = 0
            max_tool_rounds = resolve_call_limits(spec).max_tool_rounds
            while llm_result.tool_calls and tool_rounds < max_tool_rounds:
                tool_rounds += 1
                context.conversation.add_assistant_message(
                    content=llm_result.text,
                    tool_calls=[tc.model_dump() for tc in llm_result.tool_calls]
                )
                for tc in llm_result.tool_calls:
                    tool_calls_executed += 1
                    yield {"type": "tool", "status": "started", "tool_name": tc.tool_name}
                    self.emitter.emit(
                        RuntimeEventType.TOOL_CALL_STARTED, **ids,
                        payload={"call_id": tc.id, "tool_name": tc.tool_name, "arguments": tc.arguments}
                    )
                    tool_result = self.tool_executor.execute_tool(
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        enabled_tool_ids=context.active_tools,
                        client_id=context.client_id
                    )
                    self.emitter.emit(
                        RuntimeEventType.TOOL_CALL_COMPLETED, **ids,
                        payload={"call_id": tc.id, "success": tool_result.success, "data": tool_result.data, "error": tool_result.error}
                    )
                    yield {"type": "tool", "status": "completed", "tool_name": tc.tool_name, "success": tool_result.success}
                    import json
                    context.conversation.add_tool_result(
                        tool_call_id=tc.id,
                        content=json.dumps(tool_result.data if tool_result.success else {"error": tool_result.error}),
                        tool_name=tc.tool_name
                    )

                if streamed_parts and not streamed_parts[-1].endswith((" ", "\n")):
                    # Separate any pre-tool text from the continuation in the chat bubble
                    streamed_parts.append(" ")
                    yield {"type": "delta", "text": " "}
                llm_result = yield from run_llm(available_tools_list if tool_rounds < max_tool_rounds else None)

            assistant_text = llm_result.text or getattr(spec.conversation, "fallback_response", None) or "I understand. How else may I assist you?"
            if not llm_result.text:
                streamed_parts.append(assistant_text)
                yield {"type": "delta", "text": assistant_text}
            context.conversation.add_assistant_message(content=assistant_text)
            self.emitter.emit(RuntimeEventType.ASSISTANT_RESPONSE, **ids, payload={"text": assistant_text})
        finally:
            event_records = self.emitter.drain_buffer()

        bind = self.db.get_bind()
        yield {
            "type": "done",
            "transcript": user_text,
            "assistant_response": assistant_text,
            "display_text": "".join(streamed_parts).strip(),
            "tool_calls_executed": tool_calls_executed,
            "usage": context.usage_tracker.get_summary(),
            "events": event_records,
            "persist": lambda: persist_turn(bind, session_id, context, event_records),
        }

    def process_turn(
        self,
        session_id: str,
        input_audio_or_text: Any,
        synthesize_audio: bool = True,
        defer_persistence: bool = False
    ) -> Dict[str, Any]:
        """
        Executes a single conversational turn through the runtime pipeline:
        STT -> Transcript -> LLM -> Tool Call Loop -> Assistant Response -> TTS -> Events -> Usage.

        synthesize_audio=False skips TTS (text chat turns never play the audio).
        defer_persistence=True keeps the database off the critical path: the result contains a
        "persist" callable that writes the turn's events and session state in one transaction.
        """
        context, session_record = self._resolve_turn_context(session_id, require_record=not defer_persistence)

        spec = context.agent_spec
        stt_p = self.registry.get_stt(spec.providers.stt)
        llm_p = self.registry.get_llm(spec.providers.llm)
        tts_p = self.registry.get_tts(spec.providers.tts)

        self.emitter.start_buffering()
        try:
            # 1. USER SPEECH & STT
            self.emitter.emit(
                RuntimeEventType.USER_SPEECH_STARTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id
            )

            stt_result = stt_p.process_audio(input_audio_or_text)
            user_text = stt_result.text
            context.usage_tracker.record_stt(2.5)  # deterministic mock STT duration

            self.emitter.emit(
                RuntimeEventType.USER_TRANSCRIPT_FINAL,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"text": user_text, "confidence": stt_result.confidence}
            )

            # Add user turn to conversation history
            context.conversation.add_user_message(user_text)

            # 2. LLM INVOCATION & TOOL EXECUTION LOOP
            self.emitter.emit(
                RuntimeEventType.LLM_REQUEST_STARTED,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id
            )

            available_tools_list = describe_tools(self.db, context.active_tools)
            llm_result = llm_p.generate(
                system_instruction=context.conversation.system_instruction,
                messages=context.conversation.to_llm_messages(),
                available_tools=available_tools_list
            )

            # Record LLM Usage
            context.usage_tracker.record_llm(
                llm_result.usage.get("input_tokens", 0),
                llm_result.usage.get("output_tokens", 0)
            )

            self.emitter.emit(
                RuntimeEventType.LLM_RESPONSE,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={
                    "has_tool_calls": len(llm_result.tool_calls) > 0,
                    "finish_reason": llm_result.finish_reason
                }
            )

            tool_calls_executed = 0

            # Handle tool calling loop
            tool_rounds = 0
            max_tool_rounds = resolve_call_limits(spec).max_tool_rounds
            while llm_result.tool_calls and tool_rounds < max_tool_rounds:
                tool_rounds += 1
                # Append assistant message with tool calls
                context.conversation.add_assistant_message(
                    content=llm_result.text,
                    tool_calls=[tc.model_dump() for tc in llm_result.tool_calls]
                )

                for tc in llm_result.tool_calls:
                    tool_calls_executed += 1
                    self.emitter.emit(
                        RuntimeEventType.TOOL_CALL_STARTED,
                        session_id=session_id,
                        agent_id=context.agent_id,
                        agent_version_id=context.agent_version_id,
                        client_id=context.client_id,
                        payload={"call_id": tc.id, "tool_name": tc.tool_name, "arguments": tc.arguments}
                    )

                    tool_result = self.tool_executor.execute_tool(
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        arguments=tc.arguments,
                        enabled_tool_ids=context.active_tools,
                        client_id=context.client_id
                    )

                    self.emitter.emit(
                        RuntimeEventType.TOOL_CALL_COMPLETED,
                        session_id=session_id,
                        agent_id=context.agent_id,
                        agent_version_id=context.agent_version_id,
                        client_id=context.client_id,
                        payload={
                            "call_id": tc.id,
                            "success": tool_result.success,
                            "data": tool_result.data,
                            "error": tool_result.error
                        }
                    )

                    # Add tool result to conversation
                    import json
                    result_content = json.dumps(tool_result.data if tool_result.success else {"error": tool_result.error})
                    context.conversation.add_tool_result(
                        tool_call_id=tc.id,
                        content=result_content,
                        tool_name=tc.tool_name
                    )

                # LLM Continuation after tool results
                llm_result = llm_p.generate(
                    system_instruction=context.conversation.system_instruction,
                    messages=context.conversation.to_llm_messages(),
                    available_tools=available_tools_list if tool_rounds < max_tool_rounds else None
                )
                context.usage_tracker.record_llm(
                    llm_result.usage.get("input_tokens", 0),
                    llm_result.usage.get("output_tokens", 0)
                )

            # 3. ASSISTANT RESPONSE & TTS
            assistant_text = llm_result.text or getattr(spec.conversation, "fallback_response", None) or "I understand. How else may I assist you?"
            context.conversation.add_assistant_message(content=assistant_text)

            self.emitter.emit(
                RuntimeEventType.ASSISTANT_RESPONSE,
                session_id=session_id,
                agent_id=context.agent_id,
                agent_version_id=context.agent_version_id,
                client_id=context.client_id,
                payload={"text": assistant_text}
            )

            audio_duration_seconds = 0.0
            if synthesize_audio:
                self.emitter.emit(
                    RuntimeEventType.TTS_STARTED,
                    session_id=session_id,
                    agent_id=context.agent_id,
                    agent_version_id=context.agent_version_id,
                    client_id=context.client_id,
                    payload={"text": assistant_text, "voice_id": spec.voice.voice_id}
                )

                audio_res = tts_p.synthesize(
                    text=assistant_text,
                    voice_id=spec.voice.voice_id,
                    speed=spec.voice.speed,
                    language=spec.languages.primary
                )
                audio_duration_seconds = audio_res.duration_seconds
                context.usage_tracker.record_tts(audio_duration_seconds, characters=len(assistant_text))

                self.emitter.emit(
                    RuntimeEventType.TTS_COMPLETED,
                    session_id=session_id,
                    agent_id=context.agent_id,
                    agent_version_id=context.agent_version_id,
                    client_id=context.client_id,
                    payload={"duration_seconds": audio_duration_seconds, "format": audio_res.format}
                )
        finally:
            event_records = self.emitter.drain_buffer()

        usage = context.usage_tracker.get_summary()
        result: Dict[str, Any] = {
            "session_id": session_id,
            "transcript": user_text,
            "assistant_response": assistant_text,
            "audio_duration_seconds": audio_duration_seconds,
            "tool_calls_executed": tool_calls_executed,
            "usage": usage,
            "events": event_records,
        }

        if defer_persistence:
            bind = self.db.get_bind()
            result["persist"] = lambda: persist_turn(bind, session_id, context, event_records)
        else:
            for record in event_records:
                self.db.add(record)
            _apply_turn_state(session_record, context)
            self.db.commit()
            result["usage"] = session_record.usage_json

        return result

    def end_session(self, session_id: str) -> RuntimeSession:
        """
        Gracefully terminates an active voice session, records duration and usage metrics.
        """
        session_record = self.session_repo.get_by_id(session_id)
        if not session_record:
            raise NotFoundException("RuntimeSession", session_id)

        # Idempotent termination: if already completed or failed, return cleanly
        if session_record.status in (SessionStatus.COMPLETED.value, SessionStatus.FAILED.value):
            self._contexts.pop(session_id, None)
            return session_record

        # Transition to ENDING
        validate_session_transition(session_record.status, SessionStatus.ENDING.value)
        session_record.status = SessionStatus.ENDING.value
        self.session_repo.update(session_record)

        self.emitter.emit(
            RuntimeEventType.SESSION_ENDING,
            session_id=session_id,
            agent_id=session_record.agent_id,
            agent_version_id=session_record.agent_version_id,
            client_id=session_record.client_id
        )

        # Calculate duration
        now = datetime.now(timezone.utc)
        session_record.ended_at = now
        duration_sec = 0.0
        if session_record.started_at:
            duration_sec = (now - session_record.started_at.replace(tzinfo=timezone.utc)).total_seconds()

        context = self._contexts.get(session_id)
        if context:
            context.usage_tracker.record_session_duration(duration_sec)
            session_record.usage_json = context.usage_tracker.get_summary()

            # Save final compiled transcript in session metadata
            meta = dict(session_record.metadata_ or {})
            transcript_entries = [
                {"role": m.role.value, "content": m.content, "timestamp": m.timestamp.isoformat()}
                for m in context.conversation.messages
                if m.role.value in ("user", "assistant") and not m.tool_calls
            ]
            meta["transcript"] = transcript_entries
            full_text = "\n".join([f"{t['role'].capitalize()}: {t['content']}" for t in transcript_entries])
            meta["transcript_text"] = full_text
            session_record.metadata_ = meta

            # Also update linked Call record if this session originated from Telephony
            try:
                from app.models.call import Call
                call_record = self.db.query(Call).filter(Call.runtime_session_id == session_id).first()
                if call_record:
                    call_record.transcript_summary = full_text
                    call_meta = dict(call_record.metadata_ or {})
                    call_meta["transcript"] = transcript_entries
                    call_record.metadata_ = call_meta
                    self.db.add(call_record)
                    self.db.commit()
            except Exception as e:
                logger.warning(f"Could not update Call transcript for session {session_id}: {e}")

            self._contexts.pop(session_id, None)

        # Transition to COMPLETED
        validate_session_transition(session_record.status, SessionStatus.COMPLETED.value)
        session_record.status = SessionStatus.COMPLETED.value
        updated = self.session_repo.update(session_record)

        self.emitter.emit(
            RuntimeEventType.SESSION_COMPLETED,
            session_id=session_id,
            agent_id=session_record.agent_id,
            agent_version_id=session_record.agent_version_id,
            client_id=session_record.client_id,
            payload={
                "ended_at": now.isoformat(),
                "duration_seconds": duration_sec,
                "usage": updated.usage_json
            }
        )

        logger.info(f"RuntimeSession '{session_id}' completed successfully.")
        return updated

    def fail_session(self, session_id: str, error_message: str) -> RuntimeSession:
        """
        Marks session as FAILED and logs failure reason.
        """
        session_record = self.session_repo.get_by_id(session_id)
        if not session_record:
            raise NotFoundException("RuntimeSession", session_id)

        validate_session_transition(session_record.status, SessionStatus.FAILED.value)
        session_record.status = SessionStatus.FAILED.value
        session_record.error_message = error_message
        session_record.ended_at = datetime.now(timezone.utc)
        updated = self.session_repo.update(session_record)

        self.emitter.emit(
            RuntimeEventType.SESSION_FAILED,
            session_id=session_id,
            agent_id=session_record.agent_id,
            agent_version_id=session_record.agent_version_id,
            client_id=session_record.client_id,
            payload={"error": error_message}
        )

        self._contexts.pop(session_id, None)
        logger.error(f"RuntimeSession '{session_id}' failed: {error_message}")
        return updated
