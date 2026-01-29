from types import SimpleNamespace

from utils.lambda_time import http_timeout_seconds, remaining_ms


def test_remaining_ms_uses_context_method():
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 4321)
    assert remaining_ms(context) == 4321


def test_remaining_ms_defaults_when_missing():
    assert remaining_ms(SimpleNamespace()) == 10000


def test_http_timeout_seconds_respects_cap_and_floor():
    context = SimpleNamespace(get_remaining_time_in_millis=lambda: 9000)
    assert http_timeout_seconds(context, cap=10, reserve_s=1, floor=1) == 8

    low_context = SimpleNamespace(get_remaining_time_in_millis=lambda: 1500)
    assert http_timeout_seconds(low_context, cap=10, reserve_s=1, floor=2) == 2

    high_context = SimpleNamespace(get_remaining_time_in_millis=lambda: 60000)
    assert http_timeout_seconds(high_context, cap=5, reserve_s=1, floor=1) == 5
