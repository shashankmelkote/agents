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

    long_padding = "a" * 3000
    responses = [
        DummyResponse(200, {"access_token": "token"}),
        DummyResponse(
            200,
            {
                "items": [
                    {
                        "start": {"dateTime": "2024-01-01T09:00:00+00:00"},
                        "end": {"dateTime": "2024-01-01T10:00:00+00:00"},
                    }
                ],
                "nextPageToken": "next-page",
                "padding": long_padding,
            },
        ),
        DummyResponse(200, {"items": []}),
    ]

    request_urls = []

    def fake_urlopen(request, *args, **kwargs):
        request_urls.append(request.full_url)
        return responses.pop(0)

    monkeypatch.setattr(google, "urlopen", fake_urlopen)
    log_calls = []

    def fake_log_json(logger, level, msg, **fields):
        log_calls.append({"level": level, "msg": msg, **fields})

    monkeypatch.setattr(google, "log_json", fake_log_json)

    provider = google.GoogleCalendarProvider()
    start = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
    slots = provider.get_free_slots("user@example.com", start, end, 30)

    assert slots == [
        {"start": "2024-01-01T10:00:00+00:00", "end": "2024-01-01T10:30:00+00:00"},
        {"start": "2024-01-01T10:30:00+00:00", "end": "2024-01-01T11:00:00+00:00"},
    ]
    assert any(call["msg"] == "google_calendar_events_request" for call in log_calls)
    response_logs = [
        call for call in log_calls if call["msg"] == "google_calendar_events_response"
    ]
    assert response_logs
    assert len(response_logs[0]["body_prefix"]) == 2000
    assert any(call["msg"] == "google_calendar_events_summary" for call in log_calls)
    assert len([url for url in request_urls if "calendar/v3/calendars" in url]) == 2


def test_google_provider_pagination_limit(monkeypatch):
    responses = [
        DummyResponse(200, {"items": [], "nextPageToken": "page-2"}),
        DummyResponse(200, {"items": [], "nextPageToken": "page-3"}),
        DummyResponse(200, {"items": [], "nextPageToken": "page-4"}),
        DummyResponse(200, {"items": [], "nextPageToken": "page-5"}),
    ]
    request_urls = []

    def fake_urlopen(request, *args, **kwargs):
        request_urls.append(request.full_url)
        return responses.pop(0)

    monkeypatch.setattr(google, "urlopen", fake_urlopen)
    monkeypatch.setattr(google, "log_json", lambda *args, **kwargs: None)

    start = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
    busy, total_events, pages_fetched = google._fetch_busy_intervals(
        access_token="token",
        calendar_id="primary",
        start=start,
        end=end,
        time_zone="UTC",
    )

    assert busy == []
    assert total_events == 0
    assert pages_fetched == 4
    assert len(request_urls) == 4
