import pytest

import handlers.worker.worker as worker


def test_worker_handler_logs_records(monkeypatch):
    log_calls = []
    monkeypatch.setattr(worker, "log_json", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    event = {"Records": [{"id": 1}, {"id": 2}]}

    result = worker.handler(event, context={})

    assert result == {"status": "ok", "records": []}
    assert len(log_calls) == 3


def test_worker_handler_failure_propagates(monkeypatch):
    def fail_log(*args, **kwargs):
        raise RuntimeError("log failure")

    monkeypatch.setattr(worker, "log_json", fail_log)

    with pytest.raises(RuntimeError):
        worker.handler({"Records": []}, context={})
