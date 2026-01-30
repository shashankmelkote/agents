from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Tuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from utils.calendar.base import (
    CalendarProvider,
    compute_free_slots,
    parse_rfc3339,
    to_rfc3339,
)
from utils.observability import get_logger, log_json
from utils.secrets import get_secret_cached

logger = get_logger(__name__)


class GoogleCalendarProvider(CalendarProvider):
    def get_free_slots(
        self, email: str, start: datetime, end: datetime, slot_minutes: int
    ) -> list[dict]:
        log_json(
            logger,
            "info",
            "calendar_free_slots_request",
            provider="google",
            email=email,
            start=start,
            end=end,
        )
        client_secret_name = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_NAME")
        if not client_secret_name:
            raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET_NAME is not set")
        user_secret_prefix = os.environ.get("GOOGLE_OAUTH_USER_SECRET_PREFIX")
        if not user_secret_prefix:
            raise ValueError("GOOGLE_OAUTH_USER_SECRET_PREFIX is not set")

        client_secret = _load_json_secret(client_secret_name)
        client_id = client_secret.get("client_id")
        client_secret_value = client_secret.get("client_secret")
        if not client_id or not client_secret_value:
            raise ValueError("Client secret missing client_id or client_secret")

        user_secret_name = f"{user_secret_prefix}{email}"
        user_secret = _load_json_secret(user_secret_name)
        refresh_token = user_secret.get("refresh_token")
        if not refresh_token:
            raise ValueError("User secret missing refresh_token")
        calendar_id = user_secret.get("calendar_id", "primary")
        time_zone = user_secret.get("time_zone")

        access_token = _exchange_refresh_token(
            client_id=client_id,
            client_secret=client_secret_value,
            refresh_token=refresh_token,
        )
        busy_intervals, total_events, pages_fetched = _fetch_busy_intervals(
            access_token=access_token,
            calendar_id=calendar_id,
            start=start,
            end=end,
            time_zone=time_zone,
        )
        log_json(
            logger,
            "debug",
            "calendar_busy_intervals",
            provider="google",
            email=email,
            count=len(busy_intervals),
        )
        slots = compute_free_slots(start, end, busy_intervals, slot_minutes)
        log_json(
            logger,
            "debug",
            "calendar_free_slots",
            provider="google",
            email=email,
            count=len(slots),
        )
        log_json(
            logger,
            "info",
            "google_calendar_events_summary",
            pages_fetched=pages_fetched,
            total_events=total_events,
            busy_intervals_count=len(busy_intervals),
            free_slots_count=len(slots),
        )
        return slots


def _load_json_secret(secret_name: str) -> Dict[str, Any]:
    try:
        secret_value = get_secret_cached(secret_name)
    except Exception as exc:
        raise ValueError(f"Missing secret: {secret_name}") from exc
    try:
        return json.loads(secret_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Secret {secret_name} is not valid JSON") from exc


def _exchange_refresh_token(*, client_id: str, client_secret: str, refresh_token: str) -> str:
    body_bytes = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode()
    response = _request_json(
        "https://oauth2.googleapis.com/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body_bytes=body_bytes,
    )
    access_token = response.get("access_token")
    if not access_token:
        raise ValueError("Token response missing access_token")
    return access_token


def _fetch_busy_intervals(
    *,
    access_token: str,
    calendar_id: str,
    start: datetime,
    end: datetime,
    time_zone: str | None,
) -> Tuple[list[dict], int, int]:
    events: list[dict] = []
    page_token: str | None = None
    page = 1
    while page <= 4:
        params: Dict[str, Any] = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 2500,
        }
        if time_zone:
            params["timeZone"] = time_zone
        if page_token:
            params["pageToken"] = page_token
        query_string = urlencode(params)
        request_url = (
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
            f"?{query_string}"
        )
        log_json(
            logger,
            "info",
            "google_calendar_events_request",
            calendar_id=calendar_id,
            time_min=params["timeMin"],
            time_max=params["timeMax"],
            page=page,
            request_url=request_url,
            query_params=params,
        )
        response = _request_calendar_events(
            request_url=request_url,
            access_token=access_token,
            page=page,
        )
        events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
        page += 1

    busy_intervals: list[dict] = []
    default_tz = start.tzinfo
    for event in events:
        event_start = _parse_event_time(event.get("start", {}), default_tz)
        event_end = _parse_event_time(event.get("end", {}), default_tz)
        if not event_start or not event_end:
            continue
        if event_end <= start or event_start >= end:
            continue
        busy_intervals.append(
            {
                "start": to_rfc3339(max(event_start, start)),
                "end": to_rfc3339(min(event_end, end)),
            }
        )
    pages_fetched = min(page, 4)
    return busy_intervals, len(events), pages_fetched


def _parse_event_time(value: Dict[str, Any], default_tz) -> datetime | None:
    if "dateTime" in value:
        dt = parse_rfc3339(value["dateTime"])
    elif "date" in value:
        dt = datetime.fromisoformat(value["date"])
    else:
        return None
    if dt.tzinfo is None and default_tz is not None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def _request_calendar_events(
    *,
    request_url: str,
    access_token: str,
    page: int,
) -> Dict[str, Any]:
    request = Request(
        request_url,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.getcode()
            body = response.read()
    except HTTPError as exc:
        status = exc.code
        body = exc.read()
        body_prefix = _truncate_body(body)
        log_json(
            logger,
            "info",
            "google_calendar_events_response",
            page=page,
            status_code=status,
            items_count=0,
            has_next_page_token=False,
            body_prefix=body_prefix,
        )
        raise ValueError(
            f"Google Calendar API error {status}: {body_prefix}"
        ) from exc

    body_prefix = _truncate_body(body)
    if status < 200 or status >= 300:
        log_json(
            logger,
            "info",
            "google_calendar_events_response",
            page=page,
            status_code=status,
            items_count=0,
            has_next_page_token=False,
            body_prefix=body_prefix,
        )
        raise ValueError(f"Google Calendar API error {status}: {body_prefix}")

    try:
        payload = json.loads(body.decode())
    except json.JSONDecodeError as exc:
        log_json(
            logger,
            "info",
            "google_calendar_events_response",
            page=page,
            status_code=status,
            items_count=0,
            has_next_page_token=False,
            body_prefix=body_prefix,
        )
        raise ValueError("Invalid JSON response from Google Calendar API") from exc

    items = payload.get("items", [])
    has_next = bool(payload.get("nextPageToken"))
    log_json(
        logger,
        "info",
        "google_calendar_events_response",
        page=page,
        status_code=status,
        items_count=len(items),
        has_next_page_token=has_next,
        body_prefix=body_prefix,
    )
    return payload


def _request_json(url: str, headers: Dict[str, str], body_bytes: bytes) -> Dict[str, Any]:
    request = Request(url, data=body_bytes, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            status = response.getcode()
            body = response.read()
    except HTTPError as exc:
        body = exc.read()
        message = _format_http_error(exc.code, body)
        raise RuntimeError(message) from exc

    if status >= 400:
        raise RuntimeError(_format_http_error(status, body))

    try:
        return json.loads(body.decode())
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid JSON response") from exc


def _format_http_error(status: int, body: bytes) -> str:
    snippet = body[:256].decode(errors="replace")
    return f"HTTP error {status}: {snippet}"


def _truncate_body(body: bytes, limit: int = 2000) -> str:
    text = body.decode(errors="replace")
    return text[:limit]
