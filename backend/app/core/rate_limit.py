"""
Small sliding-window limiter for sensitive actions (buying and releasing numbers, syncing with the carrier).
Kept in this process's memory: with several workers each enforces its own window, which is enough to stop an
accidental loop or a double-clicking user, not a determined attacker (authentication and roles do that).
"""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException

_lock = threading.Lock()
_hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)


def check(key: str, action: str, limit: int, window_s: int = 3600) -> None:
    """Counts one use of `action` by `key`; raises 429 once `limit` uses fall inside the window."""
    now = time.monotonic()
    with _lock:
        hits = _hits[(key, action)]
        while hits and now - hits[0] > window_s:
            hits.popleft()
        if len(hits) >= limit:
            retry = int(window_s - (now - hits[0])) + 1
            raise HTTPException(status_code=429, detail=f"Too many {action} requests. Try again in {max(1, retry // 60)} min.",
                                headers={"Retry-After": str(retry)})
        hits.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
