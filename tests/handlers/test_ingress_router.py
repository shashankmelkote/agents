import base64
import importlib
import json

import pytest


def _load_module(monkeypatch, queue_url="https://queue"):
    import boto3

    class FakeSqs:
        def __init__(self):
            self.calls = []

        def send_message(self, QueueUrl, MessageBody):
            self.calls.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})

    fake_sqs = FakeSqs()

    monkeypatch.setattr(boto3, "client", lambda service: fake_sqs)
    monkeypatch.setenv("INGRESS_QUEUE_URL", queue_url)

    import handlers.router.ingress_router as ingress_router

    importlib.reload(ingress_router)
    return ingress_router, fake_sqs


def test_decode_body_base64(monkeypatch):
    ingress_router, _ = _load_module(monkeypatch)
    body = base64.b64encode(b"hello").decode("utf-8")
    event = {"body": body, "isBase64Encoded": True}

    assert ingress_router._decode_body(event) == "hello"


def test_handler_enqueues_message(monkeypatch):
    ingress_router, fake_sqs = _load_module(monkeypatch)

    event = {
        "body": json.dumps({"hello": "world"}),
        "requestContext": {"requestId": "req-1"},
    }

    result = ingress_router.handler(event, context={})

    assert result["statusCode"] == 200
    assert fake_sqs.calls
    sent = json.loads(fake_sqs.calls[0]["MessageBody"])
    assert sent["requestId"] == "req-1"
    assert sent["body"] == {"hello": "world"}


def test_handler_logs_exception_on_send_failure(monkeypatch):
    ingress_router, fake_sqs = _load_module(monkeypatch)

    def fail_send_message(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingress_router, "log_exception", lambda *args, **kwargs: fake_sqs.calls.append({"log": True}))
    monkeypatch.setattr(ingress_router.sqs_client, "send_message", fail_send_message)

    event = {"body": "{}", "requestContext": {"requestId": "req-2"}}

    result = ingress_router.handler(event, context={})

    assert result["statusCode"] == 200
    assert {"log": True} in fake_sqs.calls
