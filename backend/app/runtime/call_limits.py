import re
from dataclasses import dataclass, field
from typing import Optional, Tuple
from app.core.config import settings
from app.schemas.agent_spec import CanonicalAgentSpec

# Maximum LLM -> tool -> LLM rounds per turn when the agent doesn't set its own. The final round is
# sent without tools so the model must answer in text (models often chain calls, e.g. search then update the lead).
DEFAULT_MAX_TOOL_ROUNDS = 4
# Longer utterances are real sentences ("I'm not interested in 2BHK, show me 3BHK"), never end-call phrases
END_CALL_PHRASE_MAX_WORDS = 6

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


@dataclass(frozen=True)
class CallLimits:
    """An agent's call limits with platform defaults filled in."""
    max_call_duration_s: int
    silence_reprompt_s: float
    silence_hangup_s: float
    max_reply_chars: int
    max_tool_rounds: int
    end_call_phrases: Tuple[str, ...] = field(default_factory=tuple)

    def matches_end_call_phrase(self, text: str) -> bool:
        """True when a short caller utterance is, or contains as whole words, an end-call phrase."""
        said = _normalize(text)
        if not said or len(said.split()) > END_CALL_PHRASE_MAX_WORDS:
            return False
        padded = f" {said} "
        return any(f" {phrase} " in padded for phrase in self.end_call_phrases)


def resolve_call_limits(spec: Optional[CanonicalAgentSpec]) -> CallLimits:
    limits = spec.conversation.limits if spec else None

    def pick(name: str, default):
        value = getattr(limits, name, None) if limits else None
        return default if value is None else value

    phrases = tuple(p for p in (_normalize(x) for x in (limits.end_call_phrases if limits else [])) if p)
    return CallLimits(
        max_call_duration_s=pick("max_call_duration_s", settings.CALL_MAX_DURATION_S),
        silence_reprompt_s=pick("silence_reprompt_s", settings.CALL_SILENCE_REPROMPT_S),
        silence_hangup_s=pick("silence_hangup_s", settings.CALL_SILENCE_HANGUP_S),
        max_reply_chars=pick("max_reply_chars", settings.VOICE_MAX_REPLY_CHARS),
        max_tool_rounds=pick("max_tool_rounds", DEFAULT_MAX_TOOL_ROUNDS),
        end_call_phrases=phrases,
    )
