def remaining_ms(context) -> int:
    return getattr(context, "get_remaining_time_in_millis", lambda: 10000)()


def http_timeout_seconds(
    context,
    cap: int = 10,
    reserve_s: int = 1,
    floor: int = 1,
) -> int:
    return min(cap, max(floor, remaining_ms(context) // 1000 - reserve_s))
