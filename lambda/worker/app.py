import json
import logging
from typing import Any, Dict


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    logger.info("Received %s SQS records", len(records))
    for record in records:
        logger.info("SQS record: %s", json.dumps(record))
    return {"status": "ok"}
