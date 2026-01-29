import base64
import json
import os
from typing import Any, Dict

import boto3

from utils.observability import get_logger, log_exception

logger = get_logger(__name__)

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
            log_exception(
                logger,
                "ingress_enqueue_failed",
                request_id=request_id,
                queue_url=QUEUE_URL,
            )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
