"""
Post-call extraction: after a call ends, an LLM reads the transcript and fills in the agent's
output variables (e.g. target_exam, demo_class_booked) plus a one-line summary. Results are
stored on the Call (metadata.outputs / metadata.summary) and surface in campaign results.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.runtime_event import RuntimeEvent
from app.runtime.providers.registry import default_registry

logger = logging.getLogger("choranta.services.call_outputs")

# Status values kept in Call.metadata["outputs_status"]
PENDING, DONE, FAILED, SKIPPED = "pending", "done", "failed", "skipped"

EXTRACTION_PROMPT = """You extract structured results from a finished phone call between an AI agent and a caller.
Read the transcript and return ONLY a JSON object with exactly these keys:
- "outputs": an object with one key per variable listed below. Use the variable's type
  (string, number or boolean). Use null when the caller never gave or confirmed the information;
  never guess.
- "summary": one short sentence (max 30 words) describing what happened on the call.

Variables:
{variables}
"""


def output_definitions(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The agent version's output variables (name, description, data_type, extraction_instructions)."""
    outputs = ((config or {}).get("variables") or {}).get("outputs") or []
    return [o for o in outputs if isinstance(o, dict) and o.get("name")]


def call_transcript(db: Session, call: Call) -> List[Tuple[str, str]]:
    """(speaker, text) turns of the call, from the runtime events recorded during it."""
    if not call.runtime_session_id:
        return []
    events = (
        db.query(RuntimeEvent)
        .filter(
            RuntimeEvent.session_id == call.runtime_session_id,
            RuntimeEvent.event_type.in_(("USER_TRANSCRIPT_FINAL", "ASSISTANT_RESPONSE")),
        )
        .order_by(RuntimeEvent.timestamp)
        .all()
    )
    turns = []
    for event in events:
        text = ((event.payload_json or {}).get("text") or "").strip()
        if text:
            turns.append(("Caller" if event.event_type == "USER_TRANSCRIPT_FINAL" else "Agent", text))
    return turns


def _coerce(value: Any, data_type: str) -> Any:
    if value is None or value == "":
        return None
    data_type = (data_type or "string").lower()
    if data_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "y", "1", "booked", "confirmed"):
            return True
        if text in ("false", "no", "n", "0"):
            return False
        return None
    if data_type == "number":
        try:
            number = float(str(value).replace(",", ""))
            return int(number) if number.is_integer() else number
        except ValueError:
            return None
    return str(value).strip()


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def extract_outputs(definitions: List[Dict[str, Any]], transcript: List[Tuple[str, str]], llm) -> Dict[str, Any]:
    """Runs the extraction prompt. Returns {"outputs": {...}, "summary": str}."""
    variables = "\n".join(
        f"- {d['name']} ({d.get('data_type') or 'string'}): {d.get('description') or ''}"
        + (f" Instructions: {d['extraction_instructions']}" if d.get("extraction_instructions") else "")
        for d in definitions
    ) or "(none)"
    conversation = "\n".join(f"{speaker}: {text}" for speaker, text in transcript)
    result = llm.generate(
        system_instruction=EXTRACTION_PROMPT.format(variables=variables),
        messages=[{"role": "user", "content": f"Transcript:\n{conversation}"}],
        available_tools=None,
        temperature=0.0,
    )
    data = _parse_json(result.text or "")
    raw = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
    outputs = {d["name"]: _coerce(raw.get(d["name"]), d.get("data_type")) for d in definitions}
    summary = str(data.get("summary") or "").strip()[:300]
    return {"outputs": outputs, "summary": summary}


def _set_metadata(db: Session, call: Call, **values: Any) -> None:
    metadata = dict(call.metadata_ or {})
    metadata.update(values)
    call.metadata_ = metadata
    flag_modified(call, "metadata_")
    db.commit()


def needs_extraction(db: Session, call: Call) -> bool:
    version = db.get(AgentVersion, call.agent_version_id)
    return bool(version and output_definitions(version.configuration_json or {}))


def mark_pending(db: Session, call: Call) -> bool:
    """Flags an ended call for extraction; returns False when its agent defines no outputs."""
    if not needs_extraction(db, call):
        return False
    _set_metadata(db, call, outputs_status=PENDING)
    return True


def run_extraction(db: Session, call_id: str, llm=None) -> Optional[Dict[str, Any]]:
    """Extracts and stores the call's outputs. Never raises; failures are recorded on the call."""
    call = db.get(Call, call_id)
    if not call:
        return None
    try:
        version = db.get(AgentVersion, call.agent_version_id)
        config = (version.configuration_json or {}) if version else {}
        definitions = output_definitions(config)
        transcript = call_transcript(db, call)
        if not definitions or not any(speaker == "Caller" for speaker, _ in transcript):
            # Nothing to extract, or the caller never spoke: every output is unknown
            _set_metadata(db, call, outputs={d["name"]: None for d in definitions}, outputs_status=SKIPPED)
            return call.metadata_
        if llm is None:
            provider = (settings.LLM_PROVIDER_OVERRIDE or "").strip().lower() or (config.get("providers") or {}).get("llm") or "gemini"
            llm = default_registry.get_llm(provider)
        extracted = extract_outputs(definitions, transcript, llm)
        _set_metadata(db, call, outputs=extracted["outputs"], summary=extracted["summary"], outputs_status=DONE)
        return call.metadata_
    except Exception as e:
        logger.warning(f"Output extraction failed for call {call_id}: {type(e).__name__}: {e}")
        if not db.is_active:  # a database error left the session unusable
            db.rollback()
        call = db.get(Call, call_id)
        if call:
            _set_metadata(db, call, outputs_status=FAILED, outputs_error=f"{type(e).__name__}: {e}"[:300])
        return None


def run_extraction_job(session_factory, call_id: str) -> None:
    db = session_factory()
    try:
        run_extraction(db, call_id)
    finally:
        db.close()
