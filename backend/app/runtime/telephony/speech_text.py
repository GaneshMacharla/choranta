import re
from typing import List, Optional

# Words followed by a period that do not end a sentence
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "rs", "no", "vs", "approx", "etc", "e.g", "i.e", "inc", "ltd", "sq", "ft",
}

_SENTENCE_END = re.compile(r"[.!?।]+[\"')\]]*(?=\s)")
_CLAUSE_BREAK = re.compile(r"[,;:—–](?=\s)")

# Short acknowledgements a caller says while listening; they shouldn't interrupt the agent
BACKCHANNELS = {
    "ok", "okay", "k", "hmm", "hm", "mm", "mhm", "mmhmm", "uh huh", "uhhuh", "yeah", "yes", "yep", "yup", "right",
    "sure", "fine", "alright", "all right", "got it", "i see", "oh", "ah", "achha", "acha", "accha", "haan", "han",
    "ha", "ji", "haan ji", "ji haan", "theek hai", "thik hai", "theek", "thik", "nice", "great", "cool",
    # "Hello?" while the agent talks usually means "I can hear you" / "go on", not a new question
    "hello", "hi", "hey", "hello hello", "haan hello", "hello ji",
}


def is_backchannel(text: str) -> bool:
    normalized = re.sub(r"[^a-z ]", "", text.lower()).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized in BACKCHANNELS


class SentenceChunker:
    """
    Splits streamed LLM text into speakable chunks as soon as each sentence is complete.
    The first chunk may also break at a clause (comma etc.) once it is long enough, so the
    agent starts talking sooner.
    """

    def __init__(self, first_clause_min_chars: int = 20):
        self.first_clause_min_chars = first_clause_min_chars
        self._buffer = ""
        self._emitted_any = False

    def feed(self, text: str) -> List[str]:
        self._buffer += text
        chunks: List[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            chunk = self._buffer[:cut].strip()
            self._buffer = self._buffer[cut:].lstrip()
            if chunk:
                chunks.append(chunk)
                self._emitted_any = True
        return chunks

    def flush(self) -> List[str]:
        chunk = self._buffer.strip()
        self._buffer = ""
        if chunk:
            self._emitted_any = True
            return [chunk]
        return []

    def _find_cut(self):
        for match in _SENTENCE_END.finditer(self._buffer):
            end = match.end()
            preceding = self._buffer[:match.start()].split()
            last_word = preceding[-1].lower().rstrip(".") if preceding else ""
            if self._buffer[match.start()] == "." and last_word in _ABBREVIATIONS:
                continue
            if len(self._buffer[:end].strip()) < 2:
                continue
            return end
        if not self._emitted_any:
            for match in _CLAUSE_BREAK.finditer(self._buffer):
                if match.end() >= self.first_clause_min_chars:
                    return match.end()
        return None


_MARKDOWN = re.compile(r"(\*\*|__|`+|~~|^#+\s*|^>\s*)", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_STAGE_MARKERS = re.compile(r"\[[^\]]*interrupt[^\]]*\]", re.IGNORECASE)


def clean_for_speech(text: str) -> str:
    """
    Removes things that shouldn't be read aloud (markdown, list markers, emojis, URLs, history
    markers). TTS is billed per character, so these would also cost money for no benefit.
    """
    text = _STAGE_MARKERS.sub("", text)
    text = _URL.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = _EMOJI.sub("", text)
    text = normalize_for_speech(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Sentences made only of punctuation (e.g. a stray "...") aren't worth synthesizing
    return text if re.search(r"\w", text) else ""


# ---------------------------------------------------------------------------
# Has the caller finished their thought?
# ---------------------------------------------------------------------------

# Words a caller trails off on when they are about to say more ("my budget is...", "ante...", "aur...")
_TRAILING_WORDS = {
    # English
    "and", "but", "so", "because", "or", "like", "the", "a", "an", "my", "our", "is", "are", "was", "to", "of",
    "for", "with", "in", "at", "um", "umm", "uh", "uhh", "er", "erm", "then", "also", "about", "around", "maybe",
    # Hindi (roman)
    "aur", "lekin", "par", "toh", "to", "ki", "ke", "ka", "matlab", "ya", "jaise", "phir", "mera", "meri",
    # Telugu (roman)
    "ante", "inka", "kani", "mari", "leda", "aithe", "kuda", "ani",
    # Native script
    "और", "लेकिन", "तो", "कि", "मतलब", "या", "फिर", "मेरा", "मेरी",
    "అంటే", "ఇంకా", "కానీ", "మరి", "లేదా", "అయితే", "కూడా", "నా", "మా",
}
_TRAILING_PUNCT = re.compile(r"(,|\.\.\.|…|-|–|—)\s*$")
# Telugu and Hindi put the verb last: a phrase ending on a case ending or postposition ("కౌన్సిలర్ని",
# "ఇంటికి", "office ko") usually has its verb still to come. A weaker signal than a linking word.
_CASE_ENDINGS_NATIVE = ("కి", "కు", "తో", "లో", "ని", "ను", "నుండి", "నుంచి", "వరకు", "గురించి", "కోసం",
                        "को", "से", "में", "पर", "लिए", "तक")
_CASE_WORDS_ROMAN = {"ko", "se", "mein", "par", "liye", "tak", "gurinchi", "kosam", "varaku", "nunchi"}
_EDGE_PUNCT = ".,!?;:\"'()[]…-–—।"


def _last_word(text: str) -> str:
    words = [w.strip(_EDGE_PUNCT) for w in text.split()]
    words = [w for w in words if w]
    return words[-1].lower() if words else ""


def pause_hint(text: str) -> Optional[str]:
    """
    Whether the caller probably paused mid-thought rather than finished:
    "strong" - trailing comma/ellipsis/dash, a linking or hesitation word, or a phone number cut off partway;
    "weak"   - a Telugu/Hindi phrase ending on a case ending, with its verb probably still to come;
    None     - looks finished.
    Speech-to-text ends every fragment with a full stop, so a final "." (or "।") is ignored.
    """
    text = (text or "").strip()
    if not text:
        return None
    if _TRAILING_PUNCT.search(text):
        return "strong"
    text = re.sub(r"[.।]+$", "", text).strip()
    # A phone number being read out: ends in digits and has 5-9 of them so far (a year like 2026 has 4)
    if re.search(r"\d\W*$", text):
        digits = len(re.findall(r"\d", text))
        return "strong" if 5 <= digits <= 9 else None
    word = _last_word(text)
    if not word:
        return None
    if word in _TRAILING_WORDS:
        return "strong"
    if word in _CASE_WORDS_ROMAN or (len(word) > 2 and word.endswith(_CASE_ENDINGS_NATIVE)):
        return "weak"
    return None


def looks_incomplete(text: str) -> bool:
    return pause_hint(text) is not None


# ---------------------------------------------------------------------------
# Speakable numbers, amounts, phone numbers and dates
# ---------------------------------------------------------------------------

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
_RUPEES = re.compile(r"(?:₹|\bRs\.?|\bINR)\s*(\d[\d,]*(?:\.\d+)?)(\s*(?:lakhs?|lacs?|crores?|cr|k)\b)?", re.IGNORECASE)
_PHONE = re.compile(r"(?<![\d])(?:\+91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?![\d])")
_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_YMD = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def _plain(number: float) -> str:
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _rupees(match: "re.Match[str]") -> str:
    raw, unit = match.group(1), (match.group(2) or "").strip().lower()
    if unit:
        unit = {"lac": "lakh", "lacs": "lakh", "lakhs": "lakh", "cr": "crore", "crores": "crore",
                "k": "thousand"}.get(unit, unit)
        return f"{raw} {unit} rupees"
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return match.group(0)
    if value >= 1_00_00_000:
        return f"{_plain(value / 1_00_00_000)} crore rupees"
    if value >= 1_00_000:
        return f"{_plain(value / 1_00_000)} lakh rupees"
    return f"{raw} rupees"


def _date(day: str, month: str, year: str) -> Optional[str]:
    d, m = int(day), int(month)
    if 1 <= m <= 12 and 1 <= d <= 31:
        return f"{d} {_MONTHS[m - 1]} {year}"
    return None


def normalize_for_speech(text: str) -> str:
    """
    Rewrites things TTS reads badly into how people say them: ₹ amounts ("75 lakh rupees"), phone
    numbers in digit groups with pauses, numeric dates, % and &. Anything unrecognised is left alone.
    """
    text = _RUPEES.sub(_rupees, text)
    text = _PHONE.sub(lambda m: f"{' '.join(m.group(1))}, {' '.join(m.group(2))}", text)
    text = _YMD.sub(lambda m: _date(m.group(3), m.group(2), m.group(1)) or m.group(0), text)
    text = _DMY.sub(lambda m: _date(m.group(1), m.group(2), m.group(3)) or m.group(0), text)
    text = re.sub(r"(\d)\s*%", r"\1 percent", text)
    text = re.sub(r"\s*&\s*", " and ", text)
    return text
