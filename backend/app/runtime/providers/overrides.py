from app.core.config import settings
from app.schemas.agent_spec import CanonicalAgentSpec


def apply_provider_overrides(spec: CanonicalAgentSpec) -> CanonicalAgentSpec:
    """
    Returns the spec with STT/TTS/LLM providers replaced by any *_PROVIDER_OVERRIDE settings,
    so every agent can be switched to one provider stack (e.g. Sarvam) without republishing.
    """
    updates = {}
    for kind in ("stt", "tts", "llm"):
        override = (getattr(settings, f"{kind.upper()}_PROVIDER_OVERRIDE", "") or "").strip().lower()
        if override and getattr(spec.providers, kind) != override:
            updates[kind] = override
    if not updates:
        return spec
    providers = spec.providers.model_copy(update=updates)
    spec_updates = {"providers": providers}
    if "tts" in updates:
        spec_updates["voice"] = spec.voice.model_copy(update={"provider": updates["tts"]})
    return spec.model_copy(update=spec_updates)
