import pytest
from app.services.voice_service import VoiceService, FALLBACK_CARTESIA_VOICES


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


def test_voice_service_resilient_fallback():
    """Verify VoiceService generates fallback audio without crashing on arbitrary/invalid voice id."""
    wav = VoiceService.get_voice_preview_wav("non-existent-voice-id-999")
    assert isinstance(wav, bytes)
    assert len(wav) > 44
    assert wav[:4] == b"RIFF"
