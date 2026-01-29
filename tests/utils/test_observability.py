import json
import logging
import time

from utils import observability


def test_get_logger_respects_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    logger = observability.get_logger("test-logger")
    assert logger.level == logging.DEBUG


def test_log_json_emits_payload(caplog):
    logger = logging.getLogger("observability-test")
    logger.setLevel(logging.INFO)
    with caplog.at_level(logging.INFO):
        observability.log_json(logger, "info", "hello", foo="bar")

    assert caplog.records
    payload = json.loads(caplog.records[-1].message)
    assert payload["msg"] == "hello"
    assert payload["foo"] == "bar"


def test_emit_metric_prints_emf(capsys, monkeypatch):
    monkeypatch.setenv("STAGE", "dev")
    observability.emit_metric("TestMetric", 2, unit="Count", dims={"Service": "x"})
    captured = capsys.readouterr()
    metric = json.loads(captured.out.strip())

    assert metric["TestMetric"] == 2
    assert metric["Stage"] == "dev"
    assert metric["Service"] == "x"
    assert metric["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Jarvis"


def test_elapsed_ms_returns_int():
    start = time.time()
    time.sleep(0.001)
    elapsed = observability.elapsed_ms(start)
    assert isinstance(elapsed, int)
    assert elapsed >= 0
