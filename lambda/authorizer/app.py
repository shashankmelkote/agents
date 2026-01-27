import base64
import hashlib
import hmac
import os
import time
from typing import Any, Dict

import boto3

SECRET_CACHE: Dict[str, str] = {}


def _get_secret(secret_name: str) -> str:
    if secret_name in SECRET_CACHE:
        return SECRET_CACHE[secret_name]
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    secret_value = response.get("SecretString")
    if not secret_value:
        raise ValueError("SecretString is empty")
    SECRET_CACHE[secret_name] = secret_value
    return secret_value


def _decode_body(event: Dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return body


def _wildcard_stage_resource(method_arn: str) -> str:
    if not method_arn or method_arn == "*":
        return method_arn or "*"
    arn_parts = method_arn.split(":", 5)
    if len(arn_parts) != 6:
        return method_arn
    region = arn_parts[3]
    account = arn_parts[4]
    resource = arn_parts[5]
    resource_parts = resource.split("/", 3)
    if len(resource_parts) < 3:
        return method_arn
    api_id = resource_parts[0]
    http_verb = resource_parts[2]
    resource_path = resource_parts[3] if len(resource_parts) > 3 else ""
    return (
        f"arn:aws:execute-api:{region}:{account}:{api_id}/*/{http_verb}/{resource_path}"
    )


def _policy(effect: str, resource: str) -> Dict[str, Any]:
    return {
        "principalId": "jarvis-webhook",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}
            ],
        },
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    headers = event.get("headers") or {}
    headers_lc = {key.lower(): value for key, value in headers.items() if key}
    timestamp = headers_lc.get("x-jarvis-timestamp", "")
    signature = headers_lc.get("x-jarvis-signature", "")
    method_arn = event.get("methodArn") or "*"
    allow_resource = _wildcard_stage_resource(method_arn)
    deny_resource = method_arn if method_arn != "*" else allow_resource

    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return _policy("Deny", deny_resource)

    max_skew = int(os.environ.get("MAX_SKEW_SECONDS", "300"))
    if abs(int(time.time()) - timestamp_int) > max_skew:
        return _policy("Deny", deny_resource)

    raw_body = _decode_body(event)
    secret_name = os.environ["SECRET_NAME"]
    shared_secret = _get_secret(secret_name)

    signed_payload = f"{timestamp}.{raw_body}".encode("utf-8")
    expected_sig = hmac.new(
        shared_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature or ""):
        return _policy("Deny", deny_resource)

    return _policy("Allow", allow_resource)
