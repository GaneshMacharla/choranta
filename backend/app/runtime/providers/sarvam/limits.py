"""
Stays inside the Sarvam plan's limits instead of finding them with rejected requests.

LLM requests go through a token bucket that refills steadily, the way Sarvam's own limiter does. A live call waits only
a moment and then uses the fallback model, because a caller is listening. Post-call work and drafts wait longer and
leave part of the allowance for live calls. New streaming connections are spaced out, since Sarvam rejects ones opened
in a burst even below the plan's limit. All of this is per process, so it assumes one backend worker.
"""
import asyncio
import contextvars
import threading
import time
import weakref
from contextlib import contextmanager
from typing import Iterator, Optional

from app.core.config import settings
from app.services import call_capacity

# How much of the per-minute allowance can go out at once, in seconds' worth
_BURST_SECONDS = 10.0

_background: contextvars.ContextVar[bool] = contextvars.ContextVar("sarvam_llm_background", default=False)
_lock = threading.Lock()
_tokens: Optional[float] = None
_refilled_at = 0.0
_next_ws_open: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, float]" = weakref.WeakKeyDictionary()


@contextmanager
def background_llm() -> Iterator[None]:
    """LLM requests inside this block aren't for a live caller, so they give way to those that are."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


def is_background() -> bool:
    return _background.get()


def _take_token(rate_per_s: float, capacity: float, keep: float) -> float:
    """Takes a token if more than `keep` remain: returns 0, else the seconds until enough have refilled."""
    global _tokens, _refilled_at
    now = time.monotonic()
    with _lock:
        tokens = capacity if _tokens is None else min(capacity, _tokens + (now - _refilled_at) * rate_per_s)
        _refilled_at = now
        if tokens - 1.0 >= keep:
            _tokens = tokens - 1.0
            return 0.0
        _tokens = tokens
        return (keep + 1.0 - tokens) / rate_per_s


def acquire_llm_request() -> bool:
    """Blocks until a request may go out. False = none freed up in time, so the caller should use its fallback."""
    per_minute = settings.SARVAM_LLM_REQUESTS_PER_MIN
    if per_minute <= 0:
        return True
    rate_per_s = per_minute / 60.0
    capacity = max(1.0, rate_per_s * _BURST_SECONDS)
    background = is_background()
    keep = capacity * settings.SARVAM_LLM_LIVE_RESERVE if background else 0.0
    keep = min(keep, capacity - 1.0)
    deadline = time.monotonic() + (settings.SARVAM_LLM_BACKGROUND_WAIT_S if background else settings.SARVAM_LLM_LIVE_WAIT_S)
    while True:
        wait = _take_token(rate_per_s, capacity, keep)
        if wait <= 0:
            return True
        left = deadline - time.monotonic()
        if left <= 0 or wait > left:
            return False
        time.sleep(wait)


async def wait_for_ws_open() -> None:
    """Waits for this connection's turn to open, so that several opened together don't arrive as a burst."""
    spacing = settings.SARVAM_WS_OPEN_SPACING_MS / 1000.0
    if spacing <= 0:
        return
    loop = asyncio.get_running_loop()
    now = loop.time()
    slot = max(now, _next_ws_open.get(loop, 0.0))
    _next_ws_open[loop] = slot + spacing
    if slot > now:
        await asyncio.sleep(slot - now)


def note_ws_failure(error: object) -> None:
    """Records a failed streaming connection if Sarvam closed it for going over the limit (close code 1003)."""
    text = str(error).lower()
    if "1003" in text or "rate limit" in text:
        call_capacity.record_speech_rejection("sarvam_ws_rejected")


def reset() -> None:
    """Forgets the request allowance (tests)."""
    global _tokens, _refilled_at
    with _lock:
        _tokens = None
        _refilled_at = 0.0
    _next_ws_open.clear()
