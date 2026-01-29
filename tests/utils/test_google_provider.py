import json
from datetime import datetime, timezone

import utils.calendar.google as google


class DummyResponse:
    def __init__(self, status: int, body: dict):
        self._status = status
        self._body = json.dumps(body).encode()

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_google_provider_slots(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET_NAME", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_USER_SECRET_PREFIX", "user-secret/")

    def fake_get_secret(name: str) -> str:
        if name == "client-secret":
            return json.dumps({"client_id": "id", "client_secret": "secret"})
        if name == "user-secret/user@example.com":
            return json.dumps(
                {
                    "refresh_token": "refresh",
                    "calendar_id": "primary",
                    "time_zone": "UTC",
                }
            )
        raise AssertionError(f"Unexpected secret name {name}")

    monkeypatch.setattr(google, "get_secret_cached", fake_get_secret)

    responses = [
        DummyResponse(200, {"access_token": "token"}),
        DummyResponse(
            200,
            {
                "calendars": {
                    "primary": {
                        "busy": [
                            {
                                "start": "2024-01-01T09:00:00+00:00",
                                "end": "2024-01-01T10:00:00+00:00",
                            }
                        ]
                    }
                }
            },
        ),
    ]

    def fake_urlopen(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(google, "urlopen", fake_urlopen)

    provider = google.GoogleCalendarProvider()
    start = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
    slots = provider.get_free_slots("user@example.com", start, end, 30)

    assert slots == [
        {"start": "2024-01-01T10:00:00+00:00", "end": "2024-01-01T10:30:00+00:00"},
        {"start": "2024-01-01T10:30:00+00:00", "end": "2024-01-01T11:00:00+00:00"},
    ]
