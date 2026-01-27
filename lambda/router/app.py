import base64
import json
from typing import Any, Dict


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

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
