import re
from typing import List

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

    def __init__(self, first_clause_min_chars: int = 40):
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
