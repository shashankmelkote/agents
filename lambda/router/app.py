import base64
import json
import logging
import os
from typing import Any, Dict

import boto3


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

sqs_client = boto3.client("sqs")
QUEUE_URL = os.environ.get("INGRESS_QUEUE_URL")


def _decode_body(event: Dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body).decode("utf-8")
    return body


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    raw_body = _decode_body(event)
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError:
        parsed_body = {"raw": raw_body}

    request_id = event.get("requestContext", {}).get("requestId")
    payload = {
        "requestId": request_id,
        "body": parsed_body,
    }

    if QUEUE_URL:
        try:
            sqs_client.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(payload),
            )
        except Exception:
            logger.exception("Failed to enqueue ingress event.")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
