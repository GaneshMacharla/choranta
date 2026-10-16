"""Keeping LLM input small without changing what the agent knows or says."""
import json

import pytest
from sqlalchemy.orm import Session

from app.runtime.context import RuntimeContext
from app.runtime.conversation import ConversationState, compact_json
from app.runtime.knowledge import KnowledgeIndex, _chunks
from app.runtime.telephony.speech_text import is_presence_check
from test_phase3c_telephony import _build_test_agent_spec, telephony_setup  # noqa: F401
from test_telephony_realtime import _session, _until, fakes  # noqa: F401


def test_tool_results_are_compact_and_keep_indian_text_readable():
    data = {"matches": [{"name": "Prestige Highline", "price": "95 Lakhs", "notes": None, "tags": []}],
            "message": "", "city": "హైదరాబాద్"}
    out = compact_json(data)
    assert json.loads(out) == {"matches": [{"name": "Prestige Highline", "price": "95 Lakhs"}], "city": "హైదరాబాద్"}
    assert "\\u" not in out and ", " not in out
    assert len(out) < len(json.dumps(data))


def test_old_tool_exchanges_are_dropped_but_everything_the_caller_said_is_kept():
    conv = ConversationState(system_instruction="sys")
    conv.add_user_message("I want a 3 BHK")
    conv.add_assistant_message(content="Let me check.", tool_calls=[{"id": "t1", "name": "search_properties"}])
    conv.add_tool_result("t1", '{"matches":["a very long result"]}', "search_properties")
    conv.add_assistant_message(content="Prestige Highline has one at 95 lakhs.")
    for i in range(3):
        conv.add_user_message(f"turn {i}")
        conv.add_assistant_message(content=f"reply {i}.")
    sent = conv.to_llm_messages()
    assert not any(m["role"] == "tool" for m in sent)
    assert not any(m.get("tool_calls") for m in sent)
    assert {"role": "assistant", "content": "Let me check."} in sent  # what was spoken stays
    assert [m["content"] for m in sent if m["role"] == "user"] == ["I want a 3 BHK", "turn 0", "turn 1", "turn 2"]


def test_recent_tool_exchanges_are_kept_whole():
    conv = ConversationState(system_instruction="sys")
    conv.add_user_message("Any 3 BHK?")
    conv.add_assistant_message(content="", tool_calls=[{"id": "t1", "name": "search_properties"}])
    conv.add_tool_result("t1", '{"matches":[]}', "search_properties")
    sent = conv.to_llm_messages()
    assert any(m["role"] == "tool" for m in sent) and any(m.get("tool_calls") for m in sent)


def test_long_calls_cut_old_agent_replies_to_their_first_sentence():
    conv = ConversationState()
    for i in range(12):
        conv.add_user_message(f"caller {i}")
        conv.add_assistant_message(content=f"Answer {i}. Extra detail {i}?")
    sent = conv.to_llm_messages()
    assert sent[1]["content"] == "Answer 0."                        # old: first sentence only
    assert sent[-1]["content"] == "Answer 11. Extra detail 11?"     # recent: word for word
    assert [m["content"] for m in sent if m["role"] == "user"] == [f"caller {i}" for i in range(12)]


def test_retrieval_gives_everything_when_nothing_matches():
    filler = " Amenities include a clubhouse, gym and covered parking for residents." * 10
    index = KnowledgeIndex(_chunks("Projects", f"Prestige Highline, Whitefield, 95 Lakhs.{filler}\n\n"
                                               f"Sobha Dream Acres, Panathur, 75 Lakhs.{filler}"))
    assert len(index.chunks) > 1
    assert index.search("ప్రెస్టీజ్ ధర ఎంత?") == index.chunks           # Telugu script: no keyword match, so all of it
    assert index.search("Sobha Panathur", budget=10)[0][1].startswith("Sobha")  # a match: the matching passage first


def test_fixed_instructions_are_identical_across_calls_for_caching(db: Session, telephony_setup):
    spec = _build_test_agent_spec(telephony_setup["agent"].id)
    a = RuntimeContext("s1", "a", "c", "v", spec, {"origin": "telephony_inbound", "caller": "+919000000001", "user_name": "Ravi"})
    b = RuntimeContext("s2", "a", "c", "v", spec, {"origin": "telephony_inbound", "caller": "+919000000002"})
    assert a.conversation.system_instruction == b.conversation.system_instruction
    assert "+919000000001" in a.instruction_for_turn() and "+919000000001" not in a.conversation.system_instruction
    assert a.instruction_for_turn().startswith(a.conversation.system_instruction)


def test_presence_checks_in_english_hindi_and_telugu():
    for said in ("Hello?", "Are you there?", "హలో?", "వినిపిస్తుందా?", "हेलो?", "can you hear me"):
        assert is_presence_check(said), said
    for said in ("Hello, I want a 2 BHK", "Is it near the metro?", "హలో, ధర ఎంత?"):
        assert not is_presence_check(said), said


@pytest.mark.asyncio
async def test_hello_mid_call_is_answered_without_the_llm(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    s.context.conversation.add_assistant_message(content="Got it. Which area are you looking in?")
    fakes["stt"].transcripts[640] = "Hello? Are you there?"
    try:
        await s.execute_turn(b"\x00\x00" * 320)
        await _until(lambda: fakes["tts"].spoken)
        await _until(lambda: s._turn_task is not None and s._turn_task.done())
        said = " ".join(fakes["tts"].spoken)
        assert "Which area are you looking in?" in said
        assert fakes["llm"].calls == []  # no LLM round
    finally:
        s._utterance_worker.cancel()
