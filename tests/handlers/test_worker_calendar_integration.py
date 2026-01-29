import json

import handlers.worker.worker as worker


class DummyProvider:
    def __init__(self, slots):
        self.slots = slots
        self.calls = []

    def get_free_slots(self, email, start, end, slot_minutes):
        self.calls.append((email, start, end, slot_minutes))
        return self.slots


def test_worker_attaches_calendar_slots(monkeypatch):
    slots = [{"start": "2024-01-01T10:00:00+00:00", "end": "2024-01-01T10:30:00+00:00"}]
    provider = DummyProvider(slots)
    monkeypatch.setattr(worker, "get_provider", lambda: provider)
    monkeypatch.setattr(worker, "log_json", lambda *args, **kwargs: None)
    monkeypatch.setenv("DEFAULT_TIME_ZONE", "UTC")

    event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "body": {
                            "source": "email",
                            "from": "\"Name\" <user@example.com>",
                        }
                    }
                )
            }
        ]
    }

    result = worker.handler(event, context={})

    assert provider.calls
    assert provider.calls[0][0] == "user@example.com"
    assert result["records"][0]["payload"]["body"]["calendar_slots"] == slots
