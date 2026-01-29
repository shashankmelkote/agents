import json
import os
from datetime import datetime, time, timedelta
from typing import Any, Dict
from zoneinfo import ZoneInfo

from utils.calendar.registry import get_provider
from utils.email_utils import parse_sender_email

from utils.observability import get_logger, log_json

logger = get_logger(__name__)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    records = event.get("Records", [])
    log_json(logger, "info", "sqs_records_received", count=len(records))
    processed_records = []
    for record in records:
        log_json(logger, "info", "sqs_record", record=record)
        body = record.get("body")
        if not body:
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            log_json(logger, "warning", "sqs_record_invalid_json", body=body)
            continue
        body_payload = payload.get("body", {})
        source = body_payload.get("source")
        if source == "email":
            sender = parse_sender_email(body_payload.get("from", ""))

            time_zone = os.environ.get("DEFAULT_TIME_ZONE", "America/New_York")
            zone = ZoneInfo(time_zone)
            tomorrow = datetime.now(tz=zone).date() + timedelta(days=1)

            workday_start = os.environ.get("WORKDAY_START")
            workday_end = os.environ.get("WORKDAY_END")
            if workday_start and workday_end:
                start_time = _parse_time(workday_start)
                end_time = _parse_time(workday_end)
                window_start = datetime.combine(tomorrow, start_time, tzinfo=zone)
                window_end = datetime.combine(tomorrow, end_time, tzinfo=zone)
            else:
                window_start = datetime.combine(tomorrow, time(0, 0), tzinfo=zone)
                window_end = window_start + timedelta(days=1)

            provider = get_provider()
            slots = provider.get_free_slots(sender, window_start, window_end, 30)
            log_json(
                logger,
                "info",
                "calendar_slots",
                email=sender,
                count=len(slots),
                sample=slots[:3],
            )
            body_payload["calendar_slots"] = slots
        payload["body"] = body_payload
        processed_records.append({"record": record, "payload": payload})
    return {"status": "ok", "records": processed_records}


def _parse_time(value: str) -> time:
    parsed = datetime.strptime(value, "%H:%M").time()
    return parsed
