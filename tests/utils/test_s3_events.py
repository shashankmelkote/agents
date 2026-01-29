import pytest

from utils import s3_events


def test_extract_s3_location_from_event_success():
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "my-bucket"},
                    "object": {"key": "path/to/message.eml"},
                }
            }
        ]
    }

    bucket, key = s3_events.extract_s3_location_from_event(event)

    assert bucket == "my-bucket"
    assert key == "path/to/message.eml"


def test_extract_s3_location_from_event_invalid():
    with pytest.raises(ValueError):
        s3_events.extract_s3_location_from_event({"Records": [{"not_s3": {}}]})


def test_infer_message_id_from_key():
    assert s3_events.infer_message_id_from_key("path/to/message.eml") == "message.eml"
    assert s3_events.infer_message_id_from_key("") == ""
