"""
Puts an AI employee's knowledge (its own notes / FAQs plus any shared library entries attached to it) into
its instructions, so it answers from it on every channel. Read live, so edits apply to the next conversation
without publishing a new version.
"""
from typing import Any, List

from sqlalchemy.orm import Session

KNOWLEDGE_MARKER = "Business knowledge"
MAX_KNOWLEDGE_CHARS = 8000


def _sources(db: Session, agent_id: str, spec: Any) -> List[Any]:
    from app.models.knowledge_source import KnowledgeSource, agent_knowledge_sources
    ids = set(getattr(getattr(spec, "knowledge", None), "sources", None) or [])
    if agent_id:
        ids |= {row.knowledge_source_id for row in db.query(agent_knowledge_sources.c.knowledge_source_id)
                .filter(agent_knowledge_sources.c.agent_id == agent_id).all()}
    if not ids:
        return []
    return db.query(KnowledgeSource).filter(KnowledgeSource.id.in_(ids)).order_by(KnowledgeSource.created_at).all()


def knowledge_text(db: Session, agent_id: str, spec: Any) -> str:
    parts = []
    for source in _sources(db, agent_id, spec):
        content = (getattr(source, "content", None) or "").strip()
        if content:
            parts.append(f"### {source.name}\n{content}")
    if not parts:
        return ""
    body = "\n\n".join(parts)
    if len(body) > MAX_KNOWLEDGE_CHARS:
        body = body[:MAX_KNOWLEDGE_CHARS].rsplit("\n", 1)[0] + "\n[...more knowledge was cut for length]"
    return (
        f"\n\n{KNOWLEDGE_MARKER} (use this for facts about the business; if the answer isn't here, don't guess: "
        "say you'll check and offer a callback):\n" + body
    )


def apply_knowledge(db: Session, context: Any) -> None:
    """Adds the agent's knowledge to the conversation's system instruction once."""
    conversation = context.conversation
    if KNOWLEDGE_MARKER in (conversation.system_instruction or ""):
        return
    try:
        block = knowledge_text(db, context.agent_id, context.agent_spec)
    except Exception:  # knowledge is helpful, never a reason for a call to fail
        return
    if not block:
        return
    conversation.system_instruction = (conversation.system_instruction or "") + block
    messages = getattr(conversation, "messages", None)
    if messages and str(getattr(messages[0].role, "value", messages[0].role)).lower() == "system":
        messages[0].content = conversation.system_instruction.strip()
