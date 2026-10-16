"""
An AI employee answers business facts ONLY from its knowledge base (the client's entries attached to it).

- Every agent gets a strict grounding rule, even with no knowledge attached: prices, fees, dates, timings,
  policies, offers and availability come from its knowledge or not at all (it says it will check and offers
  a callback). It never fills gaps from general knowledge or guesses.
- A small knowledge base (up to MAX_INLINE_CHARS) is given whole. A larger one is retrieved per turn: the
  passages that best match what the caller just said are looked up (a fast local keyword search, no AI) and
  added for that reply, so nothing is lost to truncation.
- A coaching centre's Course catalogue (runtime/courses.py) is part of it and always given whole, and every agent
  is told today's date in its client's timezone (runtime/today.py).

Read live, so edits apply to the next conversation without publishing a new version.
"""
import math
import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.runtime.courses import CATALOGUE_MARKER, course_catalogue
from app.runtime.today import DEFAULT_TIMEZONE, client_today, today_line

KNOWLEDGE_MARKER = "Business knowledge"
RELEVANT_MARKER = "Relevant knowledge for the caller's latest message"
MAX_INLINE_CHARS = 2500       # a knowledge base this small is given whole
RETRIEVED_CHARS = 2000        # passages added per reply when the knowledge base is larger
SAFE_WHOLE_CHARS = 8000       # up to this size, given whole whenever retrieval can't be trusted (it always used to be)
CHUNK_CHARS = 700             # passage size for retrieval

GROUNDING_RULE = (
    "Facts about the business (prices, fees, dates, batch or appointment timings, availability, offers, policies, "
    "addresses, contact details, people's names) must come ONLY from your Business knowledge, your Call Flow and the "
    "Known Lead Context. Never use general knowledge or guess to fill a gap, and never invent numbers or dates. If the "
    "answer isn't there, say you'll check with the team and offer a callback."
)

# Short words that carry no meaning for matching (English and common Hinglish/Tenglish fillers)
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "at", "for", "with",
    "what", "which", "who", "how", "when", "where", "why", "do", "does", "did", "can", "could", "i", "you", "we",
    "it", "this", "that", "me", "my", "your", "our", "there", "any", "about", "please", "tell", "ok", "okay", "yes",
    "no", "hai", "kya", "ka", "ki", "ke", "ko", "se", "aur", "ante", "inka", "naaku", "meeru", "cheppandi",
}
_WORD = re.compile(r"\w+", re.UNICODE)
# Any Indian-language script (Devanagari through Malayalam)
_INDIC = re.compile(r"[ऀ-ൿ]")


def _tokens(text: str) -> List[str]:
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(text or "")) if len(w) > 1 and w not in _STOPWORDS]


def _sources(db: Session, agent_id: str, spec: Any) -> List[Any]:
    from app.models.knowledge_source import KnowledgeSource, agent_knowledge_sources
    ids = set(getattr(getattr(spec, "knowledge", None), "sources", None) or [])
    if agent_id:
        ids |= {row.knowledge_source_id for row in db.query(agent_knowledge_sources.c.knowledge_source_id)
                .filter(agent_knowledge_sources.c.agent_id == agent_id).all()}
    if not ids:
        return []
    return db.query(KnowledgeSource).filter(KnowledgeSource.id.in_(ids)).order_by(KnowledgeSource.created_at).all()


def _chunks(title: str, content: str) -> List[Tuple[str, str]]:
    """Splits an entry into passages: each FAQ question with its answer, or paragraphs merged up to CHUNK_CHARS."""
    blocks = re.split(r"\n\s*\n|(?=\n\s*Q\s*[:.)])", content.strip())
    chunks: List[Tuple[str, str]] = []
    current = ""
    for block in (b.strip() for b in blocks):
        if not block:
            continue
        if current and len(current) + len(block) > CHUNK_CHARS:
            chunks.append((title, current))
            current = ""
        while len(block) > CHUNK_CHARS:  # a very long paragraph (e.g. from a PDF)
            cut = block.rfind(". ", 0, CHUNK_CHARS)
            cut = cut + 1 if cut > CHUNK_CHARS // 2 else CHUNK_CHARS
            chunks.append((title, block[:cut].strip()))
            block = block[cut:].strip()
        current = f"{current}\n{block}".strip() if current else block
    if current:
        chunks.append((title, current))
    return chunks


class KnowledgeIndex:
    """The agent's knowledge as passages, searchable by keyword overlap weighted by rarity (BM25-like)."""

    def __init__(self, chunks: List[Tuple[str, str]]):
        self.chunks = chunks
        self._total_chars = sum(len(text) for _, text in chunks)
        self._tokens = [Counter(_tokens(f"{title} {text}")) for title, text in chunks]
        df = Counter(t for counts in self._tokens for t in counts)
        n = max(1, len(chunks))
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, budget: int = RETRIEVED_CHARS) -> List[Tuple[str, str]]:
        # Knowledge small enough to have always been given whole is still given whole whenever retrieval can't be
        # trusted, so trimming it never costs the agent a fact:
        # - the caller speaks Telugu/Hindi script, which can't be matched reliably against English knowledge
        #   (a stray "BHK" would pick the wrong passages)
        # - nothing matched what they said
        small = self._total_chars <= SAFE_WHOLE_CHARS
        if small and _INDIC.search(query or ""):
            return list(self.chunks)
        words = set(_tokens(query))
        scored = []
        for i, counts in enumerate(self._tokens):
            score = sum(self._idf.get(w, 0.0) * min(counts[w], 3) for w in words if w in counts)
            if score > 0:
                scored.append((score, i))
        if not scored and small:
            return list(self.chunks)
        order = [i for _, i in sorted(scored, key=lambda s: (-s[0], s[1]))] or list(range(len(self.chunks)))
        picked, used = [], 0
        for i in order:
            title, text = self.chunks[i]
            if used + len(text) > budget and picked:
                break
            picked.append((title, text))
            used += len(text)
        return picked


def _format(chunks: List[Tuple[str, str]]) -> str:
    parts, last_title = [], None
    for title, text in chunks:
        parts.append(text if title == last_title else f"### {title}\n{text}")
        last_title = title
    return "\n\n".join(parts)


def build_knowledge(db: Session, agent_id: str, spec: Any, catalogue: str = "") -> Tuple[str, Optional[KnowledgeIndex]]:
    """
    The knowledge block for the instructions, and an index when the knowledge is too big to give whole.
    A course catalogue, when the client has one, is always given whole ahead of the other entries.
    """
    entries = [(s.name, (getattr(s, "content", None) or "").strip()) for s in _sources(db, agent_id, spec)]
    entries = [(name, content) for name, content in entries if content]
    catalogue = f"\n{catalogue}" if catalogue else ""
    if not entries and not catalogue:
        return (
            f"\n\n{KNOWLEDGE_MARKER}: none has been added for this AI employee. {GROUNDING_RULE}",
            None,
        )
    header = f"\n\n{KNOWLEDGE_MARKER} (your only source of business facts). {GROUNDING_RULE}"
    total = sum(len(content) for _, content in entries)
    if total <= MAX_INLINE_CHARS:
        body = "\n\n".join(f"### {name}\n{content}" for name, content in entries)
        return header + catalogue + (f"\n{body}" if body else ""), None
    index = KnowledgeIndex([chunk for name, content in entries for chunk in _chunks(name, content)])
    titles = ", ".join(name for name, _ in entries)
    return (
        f"{header} It covers: {titles}. "
        f"For each reply you are given the passages that match the caller's latest message under "
        f"\"{RELEVANT_MARKER}\"; if what they asked isn't in those passages, treat it as not known."
        + (f" The {CATALOGUE_MARKER} below is always complete." if catalogue else "") + catalogue,
        index,
    )


def apply_knowledge(db: Session, context: Any) -> None:
    """Adds today's date and the knowledge block (and grounding rule) to the conversation's system instruction once."""
    conversation = context.conversation
    if KNOWLEDGE_MARKER in (conversation.system_instruction or ""):
        return
    client_id = getattr(context, "client_id", None)
    try:
        today = client_today(db, client_id)
        block, index = build_knowledge(db, context.agent_id, context.agent_spec, course_catalogue(db, client_id, today))
    except Exception:  # knowledge is helpful, never a reason for a call to fail
        today = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
        block, index = f"\n\n{KNOWLEDGE_MARKER}: unavailable right now. {GROUNDING_RULE}", None
    context.knowledge_index = index
    conversation.system_instruction = (conversation.system_instruction or "") + block
    # The date changes daily, so it goes with the per-call details after the cacheable fixed instructions
    context.call_details = getattr(context, "call_details", "") + today_line(today)
    messages = getattr(conversation, "messages", None)
    if messages and str(getattr(messages[0].role, "value", messages[0].role)).lower() == "system":
        messages[0].content = conversation.system_instruction.strip()


def relevant_knowledge(index: Optional[KnowledgeIndex], query: str) -> str:
    """The passages to add for one reply ("" when the whole knowledge base is already in the instructions)."""
    if index is None or not index.chunks:
        return ""
    return f"\n\n{RELEVANT_MARKER}:\n{_format(index.search(query))}"
