import math
from typing import Any, Dict, Optional

from app.core.config import settings


def _round(value: float) -> float:
    return round(value, 4)


def estimate_call_cost(duration_seconds: Optional[float], usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Estimated cost of one phone call in INR, from the rates in settings.

    - Telephony: carrier per-minute rate, billed in pulses (Exotel bills per started minute by default)
    - Speech-to-text: caller audio sent for transcription
    - Text-to-speech: agent audio synthesized
    - LLM: input/output tokens
    USD-priced providers are converted with USD_TO_INR.
    """
    usage = usage or {}
    duration = max(0.0, float(duration_seconds or 0.0))
    fx = settings.USD_TO_INR

    pulse = max(1, settings.TELEPHONY_BILLING_PULSE_SECONDS)
    billed_seconds = math.ceil(duration / pulse) * pulse if duration > 0 else 0
    telephony = billed_seconds / 60.0 * settings.TELEPHONY_RATE_PER_MINUTE_INR

    stt = float(usage.get("stt_seconds") or 0.0) / 60.0 * settings.STT_USD_PER_MINUTE * fx
    tts = float(usage.get("tts_seconds") or 0.0) / 60.0 * settings.TTS_USD_PER_MINUTE * fx
    input_millions = int(usage.get("llm_input_tokens") or 0) / 1_000_000
    output_millions = int(usage.get("llm_output_tokens") or 0) / 1_000_000
    llm_provider = usage.get("llm_provider") or "gemini"
    if llm_provider == "sarvam":  # Sarvam bills in rupees
        llm = input_millions * settings.SARVAM_INPUT_INR_PER_MILLION_TOKENS + output_millions * settings.SARVAM_OUTPUT_INR_PER_MILLION_TOKENS
    else:
        llm = (
            input_millions * settings.LLM_INPUT_USD_PER_MILLION_TOKENS
            + output_millions * settings.LLM_OUTPUT_USD_PER_MILLION_TOKENS
        ) * fx

    total = telephony + stt + tts + llm
    minutes = duration / 60.0
    return {
        "currency": "INR",
        "estimated": True,
        "duration_seconds": round(duration, 2),
        "billed_minutes": round(billed_seconds / 60.0, 2),
        "breakdown": {
            "telephony": _round(telephony),
            "speech_to_text": _round(stt),
            "text_to_speech": _round(tts),
            "llm": _round(llm),
        },
        "total": _round(total),
        # Cost per minute of actual conversation (pulse rounding makes very short calls look pricier)
        "per_minute": _round(total / minutes) if minutes > 0 else None,
        "llm_provider": llm_provider,
        "rates": {
            "telephony_per_minute_inr": settings.TELEPHONY_RATE_PER_MINUTE_INR,
            "billing_pulse_seconds": pulse,
            "stt_usd_per_minute": settings.STT_USD_PER_MINUTE,
            "tts_usd_per_minute": settings.TTS_USD_PER_MINUTE,
            "llm_input_usd_per_million_tokens": settings.LLM_INPUT_USD_PER_MILLION_TOKENS,
            "llm_output_usd_per_million_tokens": settings.LLM_OUTPUT_USD_PER_MILLION_TOKENS,
            "sarvam_input_inr_per_million_tokens": settings.SARVAM_INPUT_INR_PER_MILLION_TOKENS,
            "sarvam_output_inr_per_million_tokens": settings.SARVAM_OUTPUT_INR_PER_MILLION_TOKENS,
            "usd_to_inr": fx,
        },
    }
