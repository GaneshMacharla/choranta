import pytest
from app.services.voice_service import VoiceService, FALLBACK_CARTESIA_VOICES


@pytest.fixture(autouse=True)
def offline_cartesia(monkeypatch):
    """Previews never call the real Cartesia API in tests."""
    from app.services import voice_service

    class FakeTTS:
        def __init__(self, api_key=None):
            pass

        def synthesize(self, text, voice_id=None, speed=1.0, language=None):
            return type("R", (), {"audio_bytes": bytes(200)})()

    monkeypatch.setattr(voice_service, "CartesiaTTSProvider", FakeTTS)
    monkeypatch.setattr(VoiceService, "_previews", {})


def test_list_cartesia_voices_endpoint(client, auth_headers):
    """Verify listing Cartesia voices catalog with authentication."""
    res = client.get("/api/catalogs/voices", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= len(FALLBACK_CARTESIA_VOICES)
    first = data[0]
    assert "id" in first
    assert "name" in first
    assert "gender" in first
    assert first["provider"] == "cartesia"


def test_list_cartesia_voices_gender_filter(client, auth_headers):
    """Verify filtering voices by gender."""
    res = client.get("/api/catalogs/voices?gender=feminine", headers=auth_headers)
    assert res.status_code == 200
    fem_voices = res.json()
    assert len(fem_voices) > 0
    for v in fem_voices:
        assert v["gender"] == "feminine"

    res_masc = client.get("/api/catalogs/voices?gender=masculine", headers=auth_headers)
    assert res_masc.status_code == 200
    masc_voices = res_masc.json()
    assert len(masc_voices) > 0
    for v in masc_voices:
        assert v["gender"] == "masculine"


def test_voice_preview_endpoint_with_auth_header(client, auth_headers):
    """Verify audio preview synthesis with Bearer token header."""
    voice_id = FALLBACK_CARTESIA_VOICES[0]["id"]
    res = client.get(f"/api/catalogs/voices/{voice_id}/preview", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert len(res.content) > 44  # Valid WAV header is at least 44 bytes
    assert res.content[:4] == b"RIFF"


def test_voice_preview_endpoint_with_token_query_param(client, auth_headers):
    """Verify audio preview synthesis with token query parameter (for HTML5 <audio> / new Audio)."""
    voice_id = FALLBACK_CARTESIA_VOICES[0]["id"]
    token = auth_headers["Authorization"].split(" ")[1]
    res = client.get(f"/api/catalogs/voices/{voice_id}/preview?token={token}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/wav"
    assert res.content[:4] == b"RIFF"


def test_voice_preview_unauthorized(client):
    """Verify 401 Unauthorized when no credentials or token query param are provided."""
    voice_id = FALLBACK_CARTESIA_VOICES[0]["id"]
    res = client.get(f"/api/catalogs/voices/{voice_id}/preview")
    assert res.status_code == 401


def test_cartesia_preview_speaks_the_agent_language_and_reports_failures(monkeypatch):
    """Previews use the agent's language; a failed preview is an error, never a chime posing as the voice."""
    import pytest
    from app.services import voice_service
    from app.services.sarvam_voices import PREVIEW_TEXTS

    calls = []

    class FakeTTS:
        def __init__(self, api_key=None):
            pass

        def synthesize(self, text, voice_id=None, speed=1.0, language=None):
            calls.append((voice_id, language, text))
            if voice_id == "broke":
                raise RuntimeError("Error code: 402 - quota_exceeded")
            return type("R", (), {"audio_bytes": bytes(200)})()

    monkeypatch.setattr(voice_service, "CartesiaTTSProvider", FakeTTS)
    monkeypatch.setattr(VoiceService, "_previews", {})
    wav = VoiceService.get_voice_preview_wav("siya", language="te-IN")
    assert wav[:4] == b"RIFF" and calls == [("siya", "te", PREVIEW_TEXTS["te"])]
    VoiceService.get_voice_preview_wav("siya", language="te")  # cached
    assert len(calls) == 1
    with pytest.raises(voice_service.CartesiaPreviewUnavailable, match="out of credits"):
        VoiceService.get_voice_preview_wav("broke", language="te")
