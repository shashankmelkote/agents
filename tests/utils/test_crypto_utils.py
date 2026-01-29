import pytest

from utils import crypto_utils


def test_get_secret_cache_hit(monkeypatch):
    crypto_utils.SECRET_CACHE.clear()
    crypto_utils.SECRET_CACHE["name"] = "cached"

    def fail_client(service_name):
        raise AssertionError("boto3.client should not be called on cache hit")

    monkeypatch.setattr(crypto_utils.boto3, "client", fail_client)

    assert crypto_utils.get_secret("name") == "cached"


def test_get_secret_missing_secret_string_raises(monkeypatch):
    crypto_utils.SECRET_CACHE.clear()

    class FakeClient:
        def get_secret_value(self, SecretId):
            return {"SecretString": ""}

    monkeypatch.setattr(crypto_utils.boto3, "client", lambda service: FakeClient())

    with pytest.raises(ValueError):
        crypto_utils.get_secret("name")


def test_hmac_sha256_hex():
    result = crypto_utils.hmac_sha256_hex("key", "message")
    assert result == "6e9ef29b75fffc5b7abae527d58fdadb2fe42e7219011976917343065f58ed4a"
