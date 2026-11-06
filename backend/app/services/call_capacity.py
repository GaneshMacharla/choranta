"""
How many calls Choranta can run at once, and the signals that slow outbound calling down.

Capacity is the lowest of the speech providers' limits (Sarvam's LLM is the tightest), the platform cap and the Vobiz
account's lines. One line stays free for inbound calls, because campaigns can wait and a caller can't. Outbound also
pauses briefly when Vobiz or Sarvam start rejecting requests; inbound never does.

The pause and the counters live in memory, so this assumes one backend worker, like the dial pacing in
carrier_subaccounts. Nothing here touches the database: billing supplies the live counts, capacity_stats stores totals.
"""
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from app.core.config import settings

# Longest gap between two live-call samples that still counts towards call minutes (a longer one means the
# dispatcher wasn't running, so the count in between is unknown)
_MAX_SAMPLE_GAP_S = 120.0

_lock = threading.Lock()
_outbound_paused_until = 0.0
_rejections: Deque[float] = deque()
_counters: Dict[str, float] = {}
_peak_live = 0
_last_sample: Optional[float] = None


# ---------------------------------------------------------------- capacity


def speech_capacity() -> Optional[int]:
    """Calls the Sarvam plan's limits can carry at once; None when no limit is set."""
    limits = []
    if settings.SARVAM_LLM_REQUESTS_PER_MIN > 0 and settings.SARVAM_LLM_REQUESTS_PER_CALL > 0:
        limits.append(int(settings.SARVAM_LLM_REQUESTS_PER_MIN // settings.SARVAM_LLM_REQUESTS_PER_CALL))
    if settings.SARVAM_STT_WS_LIMIT > 0:
        limits.append(settings.SARVAM_STT_WS_LIMIT)
    if settings.SARVAM_TTS_WS_LIMIT > 0:
        limits.append(settings.SARVAM_TTS_WS_LIMIT // 2)  # a call can need a second connection while one is busy
    return max(1, min(limits)) if limits else None


def total_capacity() -> int:
    """Calls of any kind the platform can run at once, whichever carrier they use."""
    speech = speech_capacity()
    cap = settings.MAX_CONCURRENT_CALLS_PLATFORM
    return cap if speech is None else min(speech, cap)


def line_capacity() -> int:
    """Calls that can run at once on the default carrier: total capacity within the Vobiz account's lines."""
    if settings.VOBIZ_MAX_CONCURRENT_CALLS > 0:
        return min(total_capacity(), settings.VOBIZ_MAX_CONCURRENT_CALLS)
    return total_capacity()


def reserved_lines() -> int:
    """Lines only inbound calls may use. With a single line there's nothing to split, so nothing is reserved."""
    return max(0, settings.INBOUND_RESERVED_LINES) if line_capacity() >= 2 else 0


def outbound_line_capacity() -> int:
    return max(0, line_capacity() - reserved_lines())


def free_for_inbound(live_calls: int, live_vobiz_calls: int) -> int:
    free = total_capacity() - live_calls
    if settings.VOBIZ_MAX_CONCURRENT_CALLS > 0:
        free = min(free, settings.VOBIZ_MAX_CONCURRENT_CALLS - live_vobiz_calls)
    return max(0, free)


def free_for_outbound(inbound_free: int) -> int:
    if outbound_pause_left() > 0:
        return 0
    return max(0, inbound_free - reserved_lines())


# ---------------------------------------------------------------- outbound pause


def pause_outbound(seconds: Optional[float] = None) -> None:
    """Stops new outbound calls for a while. Campaigns wait and retry without using up anyone's attempts."""
    global _outbound_paused_until
    length = settings.OUTBOUND_PAUSE_S if seconds is None else seconds
    with _lock:
        _outbound_paused_until = max(_outbound_paused_until, time.monotonic() + length)


def outbound_pause_left() -> float:
    return max(0.0, _outbound_paused_until - time.monotonic())


def record_speech_rejection(kind: str) -> None:
    """Sarvam refused a request (429, 503, a closed connection) or the local limiter did; enough of them pause outbound."""
    count(kind)
    window = settings.SPEECH_BACKPRESSURE_WINDOW_S
    threshold = settings.SPEECH_BACKPRESSURE_REJECTIONS
    now = time.monotonic()
    with _lock:
        _rejections.append(now)
        while _rejections and now - _rejections[0] > window:
            _rejections.popleft()
        tripped = threshold > 0 and len(_rejections) >= threshold
        if tripped:
            _rejections.clear()
    if tripped:
        pause_outbound()


# ---------------------------------------------------------------- counters (stored by capacity_stats)


def count(name: str, amount: float = 1.0) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0.0) + amount


def note_live_calls(live: int) -> None:
    """A sample of the calls running now: keeps the peak and adds up call minutes between samples."""
    global _peak_live, _last_sample
    now = time.monotonic()
    with _lock:
        _peak_live = max(_peak_live, live)
        if _last_sample is not None and now - _last_sample <= _MAX_SAMPLE_GAP_S:
            _counters["live_call_minutes"] = _counters.get("live_call_minutes", 0.0) + live * (now - _last_sample) / 60.0
        _last_sample = now


def take_counters() -> Tuple[Dict[str, float], int]:
    """Everything counted since the last call, emptied; give it back with restore_counters if it can't be stored."""
    global _peak_live
    with _lock:
        counters, peak = dict(_counters), _peak_live
        _counters.clear()
        _peak_live = 0
    return counters, peak


def restore_counters(counters: Dict[str, float], peak: int) -> None:
    global _peak_live
    with _lock:
        for name, amount in counters.items():
            _counters[name] = _counters.get(name, 0.0) + amount
        _peak_live = max(_peak_live, peak)


def reset() -> None:
    """Forgets the pause and all counters (tests)."""
    global _outbound_paused_until, _peak_live, _last_sample
    with _lock:
        _outbound_paused_until = 0.0
        _rejections.clear()
        _counters.clear()
        _peak_live = 0
        _last_sample = None
