from datetime import datetime, timezone

from utils.calendar.base import compute_free_slots


def test_compute_free_slots_splits_busy_intervals():
    start = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc)
    busy = [
        {"start": "2024-01-01T09:30:00+00:00", "end": "2024-01-01T10:00:00+00:00"}
    ]

    slots = compute_free_slots(start, end, busy, 30)

    assert slots == [
        {"start": "2024-01-01T09:00:00+00:00", "end": "2024-01-01T09:30:00+00:00"},
        {"start": "2024-01-01T10:00:00+00:00", "end": "2024-01-01T10:30:00+00:00"},
        {"start": "2024-01-01T10:30:00+00:00", "end": "2024-01-01T11:00:00+00:00"},
    ]
