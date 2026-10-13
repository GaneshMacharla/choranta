import math
from typing import Any, Dict, Optional

from app.core.config import settings


def _round(value: float) -> float:
    return round(value, 4)


def estimate_call_cost(duration_seconds: Optional[float], usage: Optional[Dict[str, Any]], pricing: Any = None) -> Dict[str, Any]:
    """
    Estimated cost of one phone call in INR, from the rates in settings.

    - Telephony: carrier per-minute rate, billed in pulses (Exotel bills per started minute by default)
    - Speech-to-text: caller audio sent for transcription
    - Text-to-speech: agent audio synthesized
    - LLM: input/output tokens
    USD-priced providers are converted with USD_TO_INR.

    The client charge is cost x (1 + profit %), in credits (1 credit = Rs 1), with profit % from `pricing`
    (a PricingSnapshot); the default from settings is used when it is not given.
    """
    usage = usage or {}
    duration = max(0.0, float(duration_seconds or 0.0))
    fx = settings.USD_TO_INR

    pulse = max(1, settings.TELEPHONY_BILLING_PULSE_SECONDS)
    billed_seconds = math.ceil(duration / pulse) * pulse if duration > 0 else 0
    telephony = billed_seconds / 60.0 * settings.TELEPHONY_RATE_PER_MINUTE_INR

    stt_seconds = float(usage.get("stt_seconds") or 0.0)
    tts_seconds = float(usage.get("tts_seconds") or 0.0)
    stt_provider = usage.get("stt_provider") or "cartesia"
    tts_provider = usage.get("tts_provider") or "cartesia"
    if stt_provider == "sarvam":  # Sarvam bills STT per second, priced per hour in rupees
        stt = stt_seconds / 3600.0 * settings.SARVAM_STT_INR_PER_HOUR
    else:
        stt = stt_seconds / 60.0 * settings.STT_USD_PER_MINUTE * fx
    if tts_provider == "sarvam":  # Sarvam bills TTS per character
        characters = int(usage.get("tts_characters") or 0) or int(tts_seconds * 15)  # ~15 chars/s if not tracked
        tts = characters / 10_000 * settings.SARVAM_TTS_INR_PER_10K_CHARS
    else:
        tts = tts_seconds / 60.0 * settings.TTS_USD_PER_MINUTE * fx
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

    minutes = duration / 60.0

    total = telephony + stt + tts + llm
    # The client pays the call's real cost plus the admin's profit %, in credits (1 credit = Rs 1)
    profit_percent = pricing.profit_percent if pricing is not None else settings.DEFAULT_PROFIT_PERCENT
    profit = total * profit_percent / 100.0
    charge_total = total + profit
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
        "profit_percent": profit_percent,
        "profit": _round(profit),
        "charge_total": _round(charge_total),
        "charge_per_minute": _round(charge_total / minutes) if minutes > 0 else None,
        "llm_provider": llm_provider,
        "stt_provider": stt_provider,
        "tts_provider": tts_provider,
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
