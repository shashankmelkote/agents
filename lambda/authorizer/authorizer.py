import hashlib
import json
import hmac
import logging
import os
import time
from typing import Any, Dict

import boto3

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

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


def _allow_resource_from_method_arn(method_arn: str) -> str:
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


def _hmac_sha256_hex(secret: str, payload: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


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
    headers_lc = {
        str(key).lower(): value for key, value in headers.items() if key is not None
    }
    timestamp = headers_lc.get("x-jarvis-timestamp")
    signature = headers_lc.get("x-jarvis-signature")
    method_arn = event.get("methodArn", "")
    request_id = (
        event.get("requestContext", {}).get("requestId")
        or event.get("requestId")
        or ""
    )
    allow_resource = _allow_resource_from_method_arn(method_arn)

    logger.info(
        "authorizer_request",
        extra={
            "request_id": request_id,
            "method_arn": method_arn,
            "header_keys": list(headers_lc.keys()),
        },
    )

    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        logger.warning(
            "authorizer_deny: invalid_timestamp",
            extra={"request_id": request_id, "method_arn": method_arn},
        )
        return _policy("Deny", event["methodArn"])

    max_skew = int(os.environ.get("MAX_SKEW_SECONDS", "300"))
    now_ts = int(time.time())
    skew = abs(now_ts - timestamp_int)

    # TODO: Revisit timestamp skew enforcement for replay protection once clients are stable.
    # For now, log skew for debugging but do not deny solely due to time drift.
    if skew > max_skew:
        logger.warning(
            "authorizer_warn: timestamp_skew",
            extra={
                "now_ts": now_ts,
                "req_ts": timestamp_int,
                "skew_seconds": skew,
                "max_skew_seconds": max_skew,
            },
        )

    try:
        secret_name = os.environ["SECRET_NAME"]
        shared_secret = _get_secret(secret_name)

        string_to_sign = f"{timestamp}.{method_arn}"
        expected_sig = _hmac_sha256_hex(shared_secret, string_to_sign)
        provided_sig = signature or ""

        logger.warning(
            json.dumps(
                {
                    "msg": "authorizer_sig_debug",
                    "methodArn": method_arn,
                    "timestamp": timestamp_int,
                    "string_to_sign_sha256": hashlib.sha256(
                        string_to_sign.encode("utf-8")
                    ).hexdigest(),
                    "provided_sig_prefix": (provided_sig or "")[:8],
                    "expected_sig_prefix": (expected_sig or "")[:8],
                }
            )
        )

        if not hmac.compare_digest(expected_sig, provided_sig):
            logger.warning(
                "authorizer_deny: signature_mismatch",
                extra={
                    "request_id": request_id,
                    "method_arn": method_arn,
                    "signature_prefix": (signature or "")[:8],
                },
            )
            return _policy("Deny", event["methodArn"])
    except Exception:
        logger.exception(
            "authorizer_exception",
            extra={"request_id": request_id, "method_arn": method_arn},
        )
        return _policy("Deny", event["methodArn"])

    return _policy("Allow", allow_resource)
