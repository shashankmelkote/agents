import pytest

from utils import http_client


class FakeResponse:
    def __init__(self, status, body):
        self._status = status
        self._body = body

    def read(self):
        return self._body

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_post_json_successful_response(monkeypatch):
    def fake_urlopen(request, timeout):
        assert timeout == 5
        assert request.method == "POST"
        assert request.full_url == "https://example.com"
        return FakeResponse(200, b"ok")

    monkeypatch.setattr(http_client, "urlopen", fake_urlopen)

    status, prefix = http_client.post_json(
        "https://example.com",
        headers={"X-Test": "1"},
        body_bytes=b"{}",
        timeout_seconds=5,
    )

    assert status == 200
    assert prefix == "ok"


def test_post_json_non_2xx_returns_body_prefix(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(500, b"error-body")

    monkeypatch.setattr(http_client, "urlopen", fake_urlopen)

    status, prefix = http_client.post_json(
        "https://example.com",
        headers={},
        body_bytes=b"{}",
        timeout_seconds=2,
    )

    assert status == 500
    assert prefix == "error-body"


def test_post_json_raises_on_urlopen_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr(http_client, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError):
        http_client.post_json(
            "https://example.com",
            headers={},
            body_bytes=b"{}",
            timeout_seconds=1,
        )
