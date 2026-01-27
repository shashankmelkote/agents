import json
import logging
import os
from typing import Any, Dict


logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def json_logger(level: str, msg: str, **fields):
    payload = {"msg": msg, **fields}
    getattr(logger, level)(json.dumps(payload, default=str))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    json_logger("info", "sqs_records_received", count=len(records))
    for record in records:
        json_logger("info", "sqs_record", record=record)
    return {"status": "ok"}
