from typing import Any, Dict

from utils.observability import get_logger, log_json

logger = get_logger(__name__)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    log_json(logger, "info", "sqs_records_received", count=len(records))
    for record in records:
        log_json(logger, "info", "sqs_record", record=record)
    return {"status": "ok"}
