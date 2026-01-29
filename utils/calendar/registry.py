import os

from utils.calendar.base import CalendarProvider
from utils.calendar.google import GoogleCalendarProvider


_PROVIDERS = {"google": GoogleCalendarProvider}


def get_provider() -> CalendarProvider:
    provider_name = os.environ.get("CALENDAR_PROVIDER", "google").lower()
    provider_class = _PROVIDERS.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown calendar provider: {provider_name}")
    return provider_class()
