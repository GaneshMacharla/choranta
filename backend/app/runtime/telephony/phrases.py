"""
Short lines the phone agent says without the LLM: fillers while it looks something up, a quick
acknowledgement when a reply is slow, silence reprompts and goodbyes.

Each has a few variants in English, Hindi and Telugu so a call never repeats the exact same line and a
Telugu call isn't interrupted by fixed English. Hindi lines are gender-neutral (the agent's gender isn't
known). Audio for each line is cached by tts_cache, so a variant is synthesized once per voice.
"""
import random
from typing import Dict, List, Optional

PHRASES: Dict[str, Dict[str, List[str]]] = {
    # While a tool runs (checking a slot, saving a lead)
    "tool_filler": {
        "en": ["One moment, let me check.", "Sure, just a second.", "Let me look that up for you.", "Give me a second."],
        "hi": ["जी, एक सेकंड दीजिए।", "एक मिनट, अभी देखते हैं।", "ठीक है, बस एक पल।"],
        "te": ["ఒక్క నిమిషం, చెక్ చేస్తాను.", "సరే, ఒక్క సెకను.", "ఉండండి, చూస్తాను."],
    },
    # The reply is taking longer than usual to start
    "slow_ack": {
        "en": ["Hmm, okay.", "Okay.", "Right."],
        "hi": ["जी, ठीक है।", "अच्छा।", "हम्म, ठीक है।"],
        "te": ["సరే.", "అలాగే.", "హా, సరే."],
    },
    # The caller has gone quiet
    "reprompt": {
        "en": ["Hello, can you hear me?", "Are you still there?", "Hello, are you still with me?"],
        "hi": ["हैलो, क्या आपको मेरी आवाज़ आ रही है?", "हैलो, आप लाइन पर हैं?"],
        "te": ["హలో, వినిపిస్తుందా?", "హలో, లైన్‌లో ఉన్నారా?"],
    },
    # Still silent after the reprompt: hang up politely
    "silence_goodbye": {
        "en": ["I'll let you go for now. Thank you, goodbye!", "Seems like a bad time. I'll call back later. Goodbye!"],
        "hi": ["लगता है अभी सही समय नहीं है। धन्यवाद, नमस्ते!", "ठीक है, फिर बात करते हैं। धन्यवाद!"],
        "te": ["ఇప్పుడు సరైన సమయం కాదేమో. ధన్యవాదాలు, మళ్ళీ మాట్లాడదాం!", "సరే, తర్వాత మాట్లాడదాం. ధన్యవాదాలు!"],
    },
    # The LLM produced nothing to say
    "fallback": {
        "en": ["Sorry, could you say that again?", "Sorry, I didn't catch that. Could you repeat it?"],
        "hi": ["माफ़ कीजिए, क्या आप फिर से बता सकते हैं?", "सॉरी, ठीक से सुनाई नहीं दिया। एक बार फिर बताइए?"],
        "te": ["క్షమించండి, మళ్ళీ చెప్తారా?", "సారీ, సరిగ్గా వినిపించలేదు. ఇంకోసారి చెప్తారా?"],
    },
    # Used when the agent has no farewell of its own
    "default_farewell": {
        "en": ["Thank you for your time. Have a great day!"],
        "hi": ["आपके समय के लिए धन्यवाद। आपका दिन शुभ हो!"],
        "te": ["మీ సమయానికి ధన్యవాదాలు. మంచి రోజు గడపండి!"],
    },
}


def _base(language: Optional[str]) -> str:
    return (language or "en").split("-")[0].lower()


def variants(kind: str, language: Optional[str]) -> List[str]:
    """All variants of a line in the language, English when there are none for it."""
    by_language = PHRASES[kind]
    return by_language.get(_base(language)) or by_language["en"]


def pick(kind: str, language: Optional[str], last: Optional[Dict[str, str]] = None) -> str:
    """A variant of the line; `last` (one per call) remembers what was said so it isn't repeated next time."""
    options = variants(kind, language)
    previous = (last or {}).get(kind)
    fresh = [o for o in options if o != previous] or options
    choice = random.choice(fresh)
    if last is not None:
        last[kind] = choice
    return choice
