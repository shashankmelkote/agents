import os
from typing import Any, Dict, Tuple


def extract_s3_location_from_event(event: Dict[str, Any]) -> Tuple[str, str]:
    records = event.get("Records") or []
    for record in records:
        s3 = record.get("s3")
        if s3:
            bucket = s3["bucket"]["name"]
            key = s3["object"]["key"]
            return bucket, key

    raise ValueError("Expected S3 ObjectCreated event with Records[].s3 data")


def infer_message_id_from_key(key: str) -> str:
    return os.path.basename(key) if key else ""
