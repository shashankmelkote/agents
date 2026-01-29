import importlib
import time

import pytest

import handlers.authorizer.authorizer as authorizer


def test_allow_resource_from_method_arn():
    assert authorizer._allow_resource_from_method_arn("*") == "*"
    assert authorizer._allow_resource_from_method_arn("") == "*"
    arn = "arn:aws:execute-api:us-east-1:123456789012:abc/dev/POST/resource"
    expected = "arn:aws:execute-api:us-east-1:123456789012:abc/*/POST/resource"
    assert authorizer._allow_resource_from_method_arn(arn) == expected


def test_policy_builder():
    policy = authorizer._policy("Allow", "resource")
    assert policy["principalId"] == "jarvis-webhook"
    assert policy["policyDocument"]["Statement"][0]["Effect"] == "Allow"


def test_handler_allows_valid_signature(monkeypatch):
    now = int(time.time())
    log_calls = []

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setattr(authorizer, "get_secret", lambda name: "shared")
    monkeypatch.setattr(authorizer, "log_json", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    method_arn = "arn:aws:execute-api:us-east-1:123456789012:abc/dev/POST/resource"
    string_to_sign = f"{now}.{method_arn}"
    signature = authorizer.hmac_sha256_hex("shared", string_to_sign)

    event = {
        "headers": {
            "x-jarvis-timestamp": str(now),
            "x-jarvis-signature": signature,
        },
        "methodArn": method_arn,
        "requestContext": {"requestId": "req-1"},
    }

    result = authorizer.handler(event, context={})

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert log_calls


def test_handler_denies_invalid_timestamp(monkeypatch):
    log_calls = []

    monkeypatch.setattr(authorizer, "log_json", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    event = {
        "headers": {
            "x-jarvis-timestamp": "invalid",
            "x-jarvis-signature": "sig",
        },
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abc/dev/POST/resource",
    }

    result = authorizer.handler(event, context={})

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert log_calls


def test_handler_denies_signature_mismatch(monkeypatch):
    log_calls = []

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setattr(authorizer, "get_secret", lambda name: "shared")
    monkeypatch.setattr(authorizer, "log_json", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    now = int(time.time())
    event = {
        "headers": {
            "x-jarvis-timestamp": str(now),
            "x-jarvis-signature": "wrong",
        },
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abc/dev/POST/resource",
    }

    result = authorizer.handler(event, context={})

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert log_calls


def test_handler_denies_on_exception(monkeypatch):
    log_calls = []

    monkeypatch.setenv("SECRET_NAME", "secret")
    monkeypatch.setattr(authorizer, "get_secret", lambda name: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(authorizer, "log_exception", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    now = int(time.time())
    event = {
        "headers": {
            "x-jarvis-timestamp": str(now),
            "x-jarvis-signature": "sig",
        },
        "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abc/dev/POST/resource",
    }

    result = authorizer.handler(event, context={})

    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert log_calls
