from app.core.config import settings
from app.runtime import greeting_language


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_english_or_mock_greeting_is_unchanged(monkeypatch):
    called = []
    monkeypatch.setattr(greeting_language.httpx, "post", lambda *a, **k: called.append(1))
    assert greeting_language.localize_greeting("Hello there", "en-IN") == "Hello there"
    assert greeting_language.localize_greeting("Hello there", "te") == "Hello there"  # tests run in mock mode
    assert not called


def test_greeting_is_translated_to_primary_language(monkeypatch):
    monkeypatch.setattr(settings, "RUNTIME_MODE", "real")
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-key")
    greeting_language._cache.clear()
    sent = {}

    def fake_post(url, json, **_):
        sent.update(json)
        return _Resp({"translated_text": "నమస్తే, నేను ACME నుండి call చేస్తున్నాను.", "source_language_code": "en-IN"})

    monkeypatch.setattr(greeting_language.httpx, "post", fake_post)
    out = greeting_language.localize_greeting("Hello, I'm calling from Acme.", "te", keep=["Acme"])
    assert out == "నమస్తే, నేను Acme నుండి call చేస్తున్నాను."
    assert sent["target_language_code"] == "te-IN"


def test_greeting_already_in_language_is_kept(monkeypatch):
    monkeypatch.setattr(settings, "RUNTIME_MODE", "real")
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-key")
    greeting_language._cache.clear()
    monkeypatch.setattr(greeting_language.httpx, "post",
                        lambda *a, **k: _Resp({"translated_text": "rewritten", "source_language_code": "te-IN"}))
    assert greeting_language.localize_greeting("నమస్తే", "te") == "నమస్తే"


def test_translation_failure_keeps_original(monkeypatch):
    monkeypatch.setattr(settings, "RUNTIME_MODE", "real")
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-key")
    greeting_language._cache.clear()

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(greeting_language.httpx, "post", boom)
    assert greeting_language.localize_greeting("Hello", "te") == "Hello"
