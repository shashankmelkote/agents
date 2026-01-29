from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Protocol


class CalendarProvider(Protocol):
    def get_free_slots(
        self, email: str, start: datetime, end: datetime, slot_minutes: int
    ) -> list[dict]:
        """Return free time slots between start and end."""


def parse_rfc3339(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def to_rfc3339(value: datetime) -> str:
    return value.isoformat()


def compute_free_slots(
    start: datetime,
    end: datetime,
    busy_intervals: Iterable[dict],
    slot_minutes: int,
) -> list[dict]:
    if end <= start:
        return []

    busy_ranges = []
    for interval in busy_intervals:
        busy_start = parse_rfc3339(interval["start"])
        busy_end = parse_rfc3339(interval["end"])
        if busy_end <= start or busy_start >= end:
            continue
        busy_ranges.append(
            (max(busy_start, start), min(busy_end, end))
        )

    busy_ranges.sort(key=lambda item: item[0])
    merged = []
    for busy_start, busy_end in busy_ranges:
        if not merged:
            merged.append([busy_start, busy_end])
            continue
        last_start, last_end = merged[-1]
        if busy_start <= last_end:
            merged[-1][1] = max(last_end, busy_end)
        else:
            merged.append([busy_start, busy_end])

    free_intervals = []
    cursor = start
    for busy_start, busy_end in merged:
        if busy_start > cursor:
            free_intervals.append((cursor, busy_start))
        cursor = max(cursor, busy_end)
    if cursor < end:
        free_intervals.append((cursor, end))

    slots: list[dict] = []
    slot_delta = timedelta(minutes=slot_minutes)
    for free_start, free_end in free_intervals:
        slot_start = free_start
        while slot_start + slot_delta <= free_end:
            slot_end = slot_start + slot_delta
            slots.append(
                {"start": to_rfc3339(slot_start), "end": to_rfc3339(slot_end)}
            )
            slot_start = slot_end
    return slots
