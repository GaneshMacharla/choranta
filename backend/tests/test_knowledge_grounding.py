"""AI employees answer business facts only from their knowledge base, retrieved per reply when it's large."""
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.knowledge_source import KnowledgeSource
from app.runtime import knowledge
from app.runtime.conversation import ConversationState


def _entry(db: Session, name: str, content: str) -> str:
    k = KnowledgeSource(id=generate_unique_id("knw", 12), name=name, type="NOTES", status="READY", content=content, meta={})
    db.add(k)
    db.commit()
    return k.id


def _context(ids):
    spec = SimpleNamespace(knowledge=SimpleNamespace(sources=ids))
    ctx = SimpleNamespace(agent_id=None, agent_spec=spec, conversation=ConversationState(system_instruction="You are Priya."),
                          knowledge_index=None)
    return ctx


def test_agent_without_knowledge_still_never_guesses(db: Session):
    ctx = _context([])
    knowledge.apply_knowledge(db, ctx)
    prompt = ctx.conversation.system_instruction
    assert "none has been added" in prompt and "ONLY from your Business knowledge" in prompt
    assert "Never use general knowledge or guess" in prompt


def test_small_knowledge_is_given_whole(db: Session):
    ctx = _context([_entry(db, "Fees", "The Snowflake course fee is 25,000 rupees.")])
    knowledge.apply_knowledge(db, ctx)
    assert "25,000 rupees" in ctx.conversation.system_instruction and ctx.knowledge_index is None


def test_large_knowledge_is_retrieved_per_reply_without_losing_anything(db: Session):
    filler = "\n\n".join(f"Module {i}: data modelling, warehouses and transformations lesson {i}." for i in range(200))
    ids = [_entry(db, "Syllabus", filler),
           _entry(db, "Fees & batches", "Q: What is the fee?\nA: The fee is 25,000 rupees in two instalments.\n\n"
                                        "Q: When is the weekend batch?\nA: Saturdays and Sundays, 10 AM to 1 PM.")]
    ctx = _context(ids)
    knowledge.apply_knowledge(db, ctx)
    assert ctx.knowledge_index is not None
    assert "25,000" not in ctx.conversation.system_instruction  # not pasted whole...
    found = knowledge.relevant_knowledge(ctx.knowledge_index, "fees ఎంత అండి?")  # Telugu-English, as callers speak
    assert "25,000 rupees" in found                                         # ...but found when asked
    weekend = knowledge.relevant_knowledge(ctx.knowledge_index, "weekend batch timings")
    assert "Saturdays and Sundays" in weekend
    assert len(found) < knowledge.RETRIEVED_CHARS + 500


def test_context_adds_relevant_passages_for_the_latest_question(db: Session):
    from app.runtime.context import RuntimeContext
    from test_telephony_realtime import _build_test_agent_spec

    ctx = RuntimeContext("s", "a", "c", "v", _build_test_agent_spec("agt_kb"), {})
    assert ctx.instruction_for_turn() == ctx.conversation.system_instruction  # small/no knowledge: nothing extra
    ctx.knowledge_index = knowledge.KnowledgeIndex([("Fees", "The fee is 25,000 rupees."), ("Address", "We are in Ameerpet.")])
    ctx.conversation.add_user_message("What is your address?")
    turn = ctx.instruction_for_turn()
    assert knowledge.RELEVANT_MARKER in turn and "Ameerpet" in turn.split(knowledge.RELEVANT_MARKER)[1].split("###")[1]
