"""Production robustness: DB connection release, dedicated thread pools, TTS vendor fallback, graceful draining."""
import asyncio
import threading

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime import draining
from app.runtime.providers.registry import default_registry
from app.runtime.telephony import session as session_module
from app.runtime.telephony.session import _SpokenSentence
from app.services.outbound_calls import OutboundCallError, place_outbound_call
from test_telephony_realtime import FakeTTS, _session, _shutdown, fakes  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def not_draining(monkeypatch):
    monkeypatch.setattr(draining, "_draining", False)
    yield


@pytest.mark.asyncio
async def test_call_gives_its_db_connection_back_between_queries(db: Session, telephony_setup, fakes):
    s = _session(db, telephony_setup)
    try:
        assert s.call_record.status == "ACTIVE"  # a read: the session holds a transaction now
        s._release_db()
        assert not db.in_transaction()
        assert s.call_record.status == "ACTIVE"  # rows stay usable after the release
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_llm_streams_run_on_their_own_pool():
    names = []

    def gen():
        names.append(threading.current_thread().name)
        yield "hi"

    items = [item async for item in session_module._iterate_in_thread(gen)]
    assert items == ["hi"] and names[0].startswith("voice-llm")


@pytest.mark.asyncio
async def test_failed_voice_falls_back_to_another_vendor(db: Session, telephony_setup, fakes, monkeypatch):
    class BrokenTTS:
        async def synthesize_stream(self, text, **kwargs):
            raise RuntimeError("provider down")
            yield b""  # pragma: no cover

    backup = FakeTTS()
    providers = {"cartesia": BrokenTTS(), "sarvam": backup}
    monkeypatch.setattr(default_registry, "get_tts", lambda name: providers[name])
    monkeypatch.setattr(settings, "VOICE_TTS_FALLBACK_PROVIDERS", "cartesia,sarvam", raising=False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "k", raising=False)
    monkeypatch.setattr(settings, "CARTESIA_API_KEY", "k", raising=False)
    s = _session(db, telephony_setup)
    try:
        s.context.agent_spec.providers.tts = "cartesia"
        assert s._fallback_tts_provider() == "sarvam"  # never the provider that just failed
        sentence = _SpokenSentence("Hello there.")
        await s._synthesize(providers["cartesia"], sentence)
        assert backup.spoken == ["Hello there."] and sentence.audio
    finally:
        await _shutdown(s)


@pytest.mark.asyncio
async def test_fallback_skips_providers_without_a_key(db: Session, telephony_setup, fakes, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_TTS_FALLBACK_PROVIDERS", "sarvam,cartesia", raising=False)
    monkeypatch.setattr(settings, "CARTESIA_API_KEY", None, raising=False)
    s = _session(db, telephony_setup)
    try:
        s.context.agent_spec.providers.tts = "sarvam"
        assert s._fallback_tts_provider() is None
    finally:
        await _shutdown(s)


def test_no_new_outbound_calls_while_draining(db: Session, monkeypatch, not_draining):
    draining.start()
    with pytest.raises(OutboundCallError) as err:
        place_outbound_call(db, destination_number="+919999999999", agent_id="a", agent_version_id="v")
    assert err.value.code == "DRAINING" and err.value.http_status == 503


def test_health_reports_draining(client, monkeypatch, not_draining):
    assert client.get("/health").status_code == 200
    draining.start()
    response = client.get("/health")
    assert response.status_code == 503 and response.json()["status"] == "draining"


@pytest.mark.asyncio
async def test_server_waits_for_live_calls_before_stopping(monkeypatch, not_draining):
    import uvicorn
    from app.serve import DrainingServer

    monkeypatch.setattr("app.serve.DRAIN_POLL_S", 0.01)
    live = {"n": 1}
    monkeypatch.setattr(draining, "live_calls", lambda: live["n"])
    server = DrainingServer(uvicorn.Config("app.main:app"))
    server._loop = asyncio.get_running_loop()

    server.handle_exit(15, None)
    await asyncio.sleep(0.05)
    assert draining.is_draining() and not server.should_exit  # still serving the live call

    live["n"] = 0
    for _ in range(100):
        if server.should_exit:
            break
        await asyncio.sleep(0.01)
    assert server.should_exit
