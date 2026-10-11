import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class CallerTurnResult(BaseModel):
    text: str
    behavior: str = "NORMAL"  # NORMAL, SILENCE, INTERRUPTION, DELAYED, REPEATED, UNEXPECTED
    simulated_delay_seconds: float = 0.0
    is_terminal: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SimulatedCaller:
    """
    Multi-turn conversation simulator that generates contextual caller utterances,
    follows goals, reacts to assistant questions, injects voice behaviors (silence,
    interruptions, repeated questions), and safely terminates conversations.
    """

    def __init__(
        self,
        scripted_turns: Optional[List[Union[str, Dict[str, Any]]]] = None,
        caller_goal: str = "",
        max_turns: int = 10,
        caller_name: str = "Alice Smith",
        caller_phone: str = "+15550209999",
        preferred_doctor: str = "Dr. Rao",
        preferred_date: str = "2026-10-10",
        preferred_slot: str = "2026-10-10 10:00 AM",
    ):
        self.scripted_turns = scripted_turns or []
        self.caller_goal = caller_goal
        self.max_turns = max_turns
        self.caller_name = caller_name
        self.caller_phone = caller_phone
        self.preferred_doctor = preferred_doctor
        self.preferred_date = preferred_date
        self.preferred_slot = preferred_slot
        self.last_caller_utterance = ""
        self.turns_completed = 0

    def next_turn(self, assistant_response: Optional[str] = None) -> CallerTurnResult:
        """
        Determines the next caller utterance given the current turn index and assistant response.
        """
        self.turns_completed += 1
        if self.turns_completed > self.max_turns:
            return CallerTurnResult(
                text="Goodbye.",
                behavior="NORMAL",
                is_terminal=True,
                metadata={"reason": "max_turns_exceeded"},
            )

        # 1. Scripted turns priority
        turn_idx = self.turns_completed - 1
        if turn_idx < len(self.scripted_turns):
            raw_turn = self.scripted_turns[turn_idx]
            turn_result = self._parse_scripted_turn(raw_turn)
            if turn_idx == len(self.scripted_turns) - 1:
                turn_result.is_terminal = True
            self.last_caller_utterance = turn_result.text
            return turn_result

        # 2. Dynamic Goal-directed simulation if script exhausted or no script provided
        turn_result = self._generate_contextual_turn(assistant_response or "")
        self.last_caller_utterance = turn_result.text
        return turn_result

    def _parse_scripted_turn(self, item: Union[str, Dict[str, Any]]) -> CallerTurnResult:
        if isinstance(item, dict):
            text = str(item.get("text", item.get("utterance", "")))
            behavior = item.get("behavior", "NORMAL")
            delay = float(item.get("delay_seconds", item.get("simulated_delay_seconds", 0.0)))
            is_terminal = bool(item.get("is_terminal", False))
            return CallerTurnResult(
                text=text,
                behavior=behavior,
                simulated_delay_seconds=delay,
                is_terminal=is_terminal,
                metadata=item,
            )

        text = str(item).strip()
        behavior = "NORMAL"
        delay = 0.0
        is_terminal = False

        # Parse behavioral directives embedded in text: [silence], [interruption], [delay:X], [unexpected]
        if text.lower() == "[silence]":
            return CallerTurnResult(text="", behavior="SILENCE", is_terminal=False)

        if text.startswith("[interruption]"):
            behavior = "INTERRUPTION"
            text = text.replace("[interruption]", "").strip()

        delay_match = re.search(r"\[delay:([0-9.]+)\]", text, re.IGNORECASE)
        if delay_match:
            delay = float(delay_match.group(1))
            behavior = "DELAYED"
            text = re.sub(r"\[delay:[0-9.]+\]", "", text).strip()

        if text.startswith("[unexpected]"):
            behavior = "UNEXPECTED"
            text = text.replace("[unexpected]", "").strip()

        if text.startswith("[repeat]"):
            behavior = "REPEATED"
            text = self.last_caller_utterance or "Could you repeat that please?"

        lower = text.lower()
        if any(term in lower for term in ["goodbye", "bye", "that's all thank you", "have a good day"]):
            is_terminal = True

        return CallerTurnResult(
            text=text,
            behavior=behavior,
            simulated_delay_seconds=delay,
            is_terminal=is_terminal,
        )

    def _generate_contextual_turn(self, assistant_response: str) -> CallerTurnResult:
        lower_resp = assistant_response.lower()

        # Check for confirmed conclusion or farewell
        if any(w in lower_resp for w in ["confirmed", "booked your appointment", "confirmation number", "recorded your inquiry"]):
            return CallerTurnResult(
                text="That's great! Thank you so much for your help. Goodbye.",
                behavior="NORMAL",
                is_terminal=True,
            )

        if any(w in lower_resp for w in ["goodbye", "have a great day", "have a wonderful day"]):
            return CallerTurnResult(
                text="Thank you, goodbye!",
                behavior="NORMAL",
                is_terminal=True,
            )

        # Check if slots are unavailable
        if any(w in lower_resp for w in ["no open slots", "no available slots", "fully booked", "unavailable"]):
            return CallerTurnResult(
                text="I see. Thank you for checking for me, I will check back next week. Goodbye.",
                behavior="NORMAL",
                is_terminal=True,
            )

        # Check if assistant is asking for date or time
        if any(w in lower_resp for w in ["what date", "which date", "what time", "preferred time"]):
            return CallerTurnResult(
                text=f"I would like {self.preferred_date} at 10:00 AM please.",
                behavior="NORMAL",
            )

        # Check if assistant is asking for name or phone
        if any(w in lower_resp for w in ["your name", "who is calling", "contact phone", "phone number"]):
            return CallerTurnResult(
                text=f"My name is {self.caller_name} and my phone number is {self.caller_phone}.",
                behavior="NORMAL",
            )

        # Check if assistant asks to confirm booking
        if any(w in lower_resp for w in ["would you like me to book", "should i confirm", "confirm that"]):
            return CallerTurnResult(
                text=f"Yes please, go ahead and book it for {self.caller_name}.",
                behavior="NORMAL",
            )

        # Check if assistant clarifies an ambiguous question
        if any(w in lower_resp for w in ["which doctor", "which provider", "what type of appointment", "department"]):
            return CallerTurnResult(
                text=f"I would like to see {self.preferred_doctor} on {self.preferred_date}.",
                behavior="NORMAL",
            )

        # Default opening or goal declaration if early turn
        if self.turns_completed == 1:
            if "hours" in self.caller_goal.lower():
                return CallerTurnResult(text="Hello, could you tell me your operating hours today?", behavior="NORMAL")
            return CallerTurnResult(
                text=f"Hello, I would like to check availability with {self.preferred_doctor}.",
                behavior="NORMAL",
            )

        # Fallback closure if assistant doesn't ask a question
        if "?" not in assistant_response:
            return CallerTurnResult(
                text="Understood. Thank you for your assistance. Goodbye.",
                behavior="NORMAL",
                is_terminal=True,
            )

        return CallerTurnResult(
            text="Yes, that works for me. Thank you.",
            behavior="NORMAL",
        )
