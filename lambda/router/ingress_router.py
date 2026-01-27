import base64
import json
import logging
import os
from typing import Any, Dict

import boto3


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def json_logger(level: str, msg: str, **fields):
    payload = {"msg": msg, **fields}
    getattr(logger, level)(json.dumps(payload, default=str))

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
            json_logger(
                "exception",
                "ingress_enqueue_failed",
                request_id=request_id,
                queue_url=QUEUE_URL,
            )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
