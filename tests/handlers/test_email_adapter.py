import io
import json
from types import SimpleNamespace

import pytest

import handlers.email_adapter.email_adapter as email_adapter


def _make_event(key="folder%2Fmessage.eml"):
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "my-bucket"},
                    "object": {"key": key},
                }
            }
        ]
    }


def _make_context(remaining_ms=10000):
    return SimpleNamespace(
        aws_request_id="req-1",
        get_remaining_time_in_millis=lambda: remaining_ms,
    )


def test_handler_success_end_to_end(monkeypatch):
    event = _make_event()
    context = _make_context()

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setenv("INGRESS_URL", "https://abc.execute-api.us-east-1.amazonaws.com/dev/ingress")

    class FakeS3:
        def __init__(self):
            self.calls = []

        def get_object(self, Bucket, Key):
            self.calls.append({"Bucket": Bucket, "Key": Key})
            return {"Body": io.BytesIO(b"raw email")}

    fake_s3 = FakeS3()

    post_calls = []
    log_calls = []
    metric_calls = []

    monkeypatch.setattr(email_adapter, "get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(
        email_adapter,
        "parse_raw_email",
        lambda raw: {
            "from": "sender@example.com",
            "subject": "Hello",
            "text": "Body",
        },
    )
    monkeypatch.setattr(email_adapter, "get_secret_cached", lambda name: "shared")
    monkeypatch.setattr(email_adapter, "get_account_id", lambda: "123456789012")
    monkeypatch.setattr(email_adapter, "build_method_arn_for_ingress", lambda *args, **kwargs: "arn")
    monkeypatch.setattr(email_adapter, "hmac_sha256_hex", lambda secret, msg: "sig")
    monkeypatch.setattr(email_adapter, "http_timeout_seconds", lambda *args, **kwargs: 5)
    monkeypatch.setattr(
        email_adapter,
        "post_json",
        lambda url, headers, body_bytes, timeout_seconds: post_calls.append(
            {
                "url": url,
                "headers": headers,
                "body": body_bytes,
                "timeout": timeout_seconds,
            }
        )
        or (200, "ok"),
    )
    monkeypatch.setattr(email_adapter, "log_json", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "log_exception", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "emit_metric", lambda *args, **kwargs: metric_calls.append((args, kwargs)))

    result = email_adapter.handler(event, context)

    assert result["statusCode"] == 200
    assert fake_s3.calls == [{"Bucket": "my-bucket", "Key": "folder/message.eml"}]
    assert post_calls
    body = json.loads(post_calls[0]["body"].decode("utf-8"))
    assert body["source"] == "email"
    assert body["s3"]["bucket"] == "my-bucket"
    assert body["s3"]["key"] == "folder/message.eml"
    assert post_calls[0]["headers"]["x-jarvis-signature"] == "sig"
    assert metric_calls
    assert log_calls


def test_handler_missing_env_var_logs_and_raises(monkeypatch):
    event = _make_event()
    context = _make_context()

    monkeypatch.delenv("SECRET_NAME", raising=False)
    monkeypatch.setenv("INGRESS_URL", "https://example.com")

    class FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(b"raw email")}

    log_calls = []

    monkeypatch.setattr(email_adapter, "get_s3_client", lambda: FakeS3())
    monkeypatch.setattr(email_adapter, "parse_raw_email", lambda raw: {"from": "a", "subject": "b", "text": "c"})
    monkeypatch.setattr(email_adapter, "log_exception", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "log_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(email_adapter, "emit_metric", lambda *args, **kwargs: None)

    with pytest.raises(KeyError):
        email_adapter.handler(event, context)

    assert log_calls


def test_handler_secret_fetch_failure_logs(monkeypatch):
    event = _make_event()
    context = _make_context()

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setenv("INGRESS_URL", "https://example.com")

    class FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(b"raw email")}

    log_calls = []

    monkeypatch.setattr(email_adapter, "get_s3_client", lambda: FakeS3())
    monkeypatch.setattr(email_adapter, "parse_raw_email", lambda raw: {"from": "a", "subject": "b", "text": "c"})
    monkeypatch.setattr(email_adapter, "get_secret_cached", lambda name: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(email_adapter, "log_exception", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "log_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(email_adapter, "emit_metric", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError):
        email_adapter.handler(event, context)

    assert log_calls


def test_handler_http_non_2xx_logs_and_raises(monkeypatch):
    event = _make_event()
    context = _make_context()

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setenv("INGRESS_URL", "https://example.com")

    class FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(b"raw email")}

    log_calls = []

    monkeypatch.setattr(email_adapter, "get_s3_client", lambda: FakeS3())
    monkeypatch.setattr(email_adapter, "parse_raw_email", lambda raw: {"from": "a", "subject": "b", "text": "c"})
    monkeypatch.setattr(email_adapter, "get_secret_cached", lambda name: "secret")
    monkeypatch.setattr(email_adapter, "get_account_id", lambda: "123")
    monkeypatch.setattr(email_adapter, "build_method_arn_for_ingress", lambda *args, **kwargs: "arn")
    monkeypatch.setattr(email_adapter, "post_json", lambda *args, **kwargs: (500, "bad"))
    monkeypatch.setattr(email_adapter, "log_exception", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "log_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(email_adapter, "emit_metric", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError):
        email_adapter.handler(event, context)

    assert log_calls


def test_handler_low_remaining_time_aborts(monkeypatch):
    event = _make_event()
    context = _make_context(remaining_ms=3000)

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setenv("INGRESS_URL", "https://example.com")

    class FakeS3:
        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(b"raw email")}

    log_calls = []

    monkeypatch.setattr(email_adapter, "get_s3_client", lambda: FakeS3())
    monkeypatch.setattr(email_adapter, "parse_raw_email", lambda raw: {"from": "a", "subject": "b", "text": "c"})
    monkeypatch.setattr(email_adapter, "log_json", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "log_exception", lambda *args, **kwargs: log_calls.append((args, kwargs)))
    monkeypatch.setattr(email_adapter, "emit_metric", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="low remaining time"):
        email_adapter.handler(event, context)

    assert any(call[0][2] == "email_adapter_abort_low_time" for call in log_calls)
