import time

import pytest
from botocore.exceptions import ClientError

from utils import secrets


def test_configure_secret_cache_sets_globals():
    logger = object()
    secrets.configure_secret_cache(logger=logger, metric_dims={"Service": "test"}, foo="bar")

    assert secrets._SECRET_LOGGER is logger
    assert secrets._SECRET_COMMON_FIELDS == {"foo": "bar"}
    assert secrets._SECRET_METRIC_DIMS == {"Service": "test"}


def test_get_secret_cached_cache_hit(monkeypatch):
    secrets._SECRET_CACHE.clear()
    now = time.time()
    secrets._SECRET_CACHE["my-secret"] = ("cached", now - 5)

    def fail_client():
        raise AssertionError("Secrets Manager should not be called on cache hit")

    monkeypatch.setattr(secrets, "get_secretsmanager_client", fail_client)
    monkeypatch.setattr(secrets, "log_json", lambda *args, **kwargs: None)

    value = secrets.get_secret_cached("my-secret", ttl_seconds=10)

    assert value == "cached"


def test_get_secret_cached_cache_miss_fetches(monkeypatch):
    secrets._SECRET_CACHE.clear()
    calls = {"count": 0}

    class FakeClient:
        def get_secret_value(self, SecretId):
            calls["count"] += 1
            return {"SecretString": "fresh"}

    monkeypatch.setattr(secrets, "get_secretsmanager_client", lambda: FakeClient())
    monkeypatch.setattr(secrets, "log_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(secrets, "emit_metric", lambda *args, **kwargs: None)

    value = secrets.get_secret_cached("my-secret", ttl_seconds=10)

    assert value == "fresh"
    assert calls["count"] == 1


def test_get_secret_cached_ttl_expiry_refetches(monkeypatch):
    secrets._SECRET_CACHE.clear()
    calls = {"count": 0}

    class FakeClient:
        def get_secret_value(self, SecretId):
            calls["count"] += 1
            return {"SecretString": f"value-{calls['count']}"}

    monkeypatch.setattr(secrets, "get_secretsmanager_client", lambda: FakeClient())
    monkeypatch.setattr(secrets, "log_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(secrets, "emit_metric", lambda *args, **kwargs: None)

    now = time.time()
    secrets._SECRET_CACHE["my-secret"] = ("stale", now - 100)

    value = secrets.get_secret_cached("my-secret", ttl_seconds=1)

    assert value == "value-1"
    assert calls["count"] == 1


def test_fetch_secret_client_error_logs_and_raises(monkeypatch):
    secrets._SECRET_CACHE.clear()
    log_calls = []

    class FakeClient:
        def get_secret_value(self, SecretId):
            error_response = {"Error": {"Code": "AccessDenied", "Message": "nope"}}
            raise ClientError(error_response, "GetSecretValue")

    monkeypatch.setattr(secrets, "get_secretsmanager_client", lambda: FakeClient())
    monkeypatch.setattr(secrets, "log_json", lambda *args, **kwargs: log_calls.append(kwargs))
    monkeypatch.setattr(secrets, "emit_metric", lambda *args, **kwargs: None)

    with pytest.raises(ClientError):
        secrets.get_secret_cached("my-secret", ttl_seconds=1)

    assert log_calls
    assert log_calls[-1]["aws_error_code"] == "AccessDenied"
