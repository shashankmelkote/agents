import json
import os
import time
from email import policy
from email.parser import BytesParser
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3

from utils.crypto_utils import get_secret, hmac_sha256_hex

ACCOUNT_ID_CACHE: Optional[str] = None


def _get_account_id() -> str:
    global ACCOUNT_ID_CACHE
    if ACCOUNT_ID_CACHE:
        return ACCOUNT_ID_CACHE
    sts = boto3.client("sts")
    ACCOUNT_ID_CACHE = sts.get_caller_identity()["Account"]
    return ACCOUNT_ID_CACHE


def _extract_s3_location(event: Dict[str, Any]) -> Tuple[str, str]:
    records = event.get("Records") or []
    for record in records:
        if "s3" in record:
            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
            return bucket, key

        ses = record.get("ses") or {}
        receipt = ses.get("receipt") or {}
        action = receipt.get("action") or {}
        bucket = action.get("bucketName") or action.get("bucket")
        key = action.get("objectKey") or action.get("objectKeyName")
        if bucket and key:
            return bucket, key

        prefix = action.get("objectKeyPrefix") or ""
        message_id = (ses.get("mail") or {}).get("messageId")
        if bucket and message_id:
            key = f"{prefix}{message_id}"
            return bucket, key

    bucket = event.get("bucket")
    key = event.get("key")
    if bucket and key:
        return bucket, key

    raise ValueError("Unable to determine S3 bucket/key from SES event")


def _get_email_text(message) -> str:
    if message.is_multipart():
        body = message.get_body(preferencelist=("plain",))
        if body:
            return body.get_content()
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="replace")
        return ""
    try:
        return message.get_content()
    except Exception:
        payload = message.get_payload(decode=True)
        return payload.decode(errors="replace") if payload else ""


def _parse_email(raw_email: bytes) -> Dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(raw_email)
    return {
        "from": message.get("From", ""),
        "subject": message.get("Subject", ""),
        "text": _get_email_text(message),
    }


def _build_method_arn(ingress_url: str) -> str:
    parsed = urlparse(ingress_url)
    host_parts = (parsed.hostname or "").split(".")
    api_id = host_parts[0] if host_parts else ""
    region = host_parts[2] if len(host_parts) > 2 else os.environ.get("AWS_REGION", "")
    account_id = _get_account_id()
    path_parts = (parsed.path or "").strip("/").split("/")
    stage = path_parts[0] if path_parts else ""
    resource_path = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""
    return (
        f"arn:aws:execute-api:{region}:{account_id}:{api_id}"
        f"/{stage}/POST/{resource_path}"
    )


def _post_ingress(payload: Dict[str, Any], ingress_url: str, secret: str) -> None:
    timestamp = str(int(time.time()))
    body = json.dumps(payload, separators=(",", ":"))
    method_arn = _build_method_arn(ingress_url)
    signature = hmac_sha256_hex(secret, f"{timestamp}.{method_arn}")

    request = Request(
        ingress_url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-jarvis-timestamp": timestamp,
            "x-jarvis-signature": signature,
        },
    )

    with urlopen(request) as response:
        response.read()


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    bucket, key = _extract_s3_location(event)
    s3_client = boto3.client("s3")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    raw_email = response["Body"].read()

    parsed_email = _parse_email(raw_email)
    payload = {
        "source": "email",
        "from": parsed_email["from"],
        "subject": parsed_email["subject"],
        "text": parsed_email["text"],
        "s3": {"bucket": bucket, "key": key},
    }

    secret_name = os.environ["SECRET_NAME"]
    shared_secret = get_secret(secret_name)
    ingress_url = os.environ["INGRESS_URL"]
    _post_ingress(payload, ingress_url, shared_secret)

    return {"statusCode": 200, "body": json.dumps({"status": "ok"})}
