"""
Graceful shutdown: once draining starts, no new outbound calls are placed and /health reports 503 (so a load
balancer stops sending traffic here), while calls already in progress carry on until they end.
"""
_draining = False


def start() -> None:
    global _draining
    _draining = True


def is_draining() -> bool:
    return _draining


def live_calls() -> int:
    """Calls in progress in this process: phone and browser test calls, plus legacy audio WebSocket sessions."""
    from app.runtime.telephony.session import active_telephony_calls
    from app.api.routes.websocket_audio import active_audio_sessions
    return len(active_telephony_calls) + len(active_audio_sessions)
