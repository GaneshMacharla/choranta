"""
Legacy Exotel numbers (bought before Vobiz): only releasing them is still needed, through services/exotel_numbers.py.
New numbers are bought on Vobiz.
"""
from app.runtime.providers.numbers.base import NumberProvider, ProviderUnavailable
from app.services import exotel_numbers


class ExotelNumberProvider(NumberProvider):
    name = "exotel"

    def __init__(self, exophone_sid: str = ""):
        self._sid = exophone_sid

    def release(self, e164: str) -> None:
        try:
            exotel_numbers.release(self._sid)
        except exotel_numbers.ExotelNumberError as exc:
            raise ProviderUnavailable(str(exc)) from exc
