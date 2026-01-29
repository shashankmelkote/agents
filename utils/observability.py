import json
import logging
import os
import time
from typing import Any, Dict, Optional


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    return logger


def log_json(logger: logging.Logger, level: str, msg: str, **fields: Any) -> None:
    payload = {"msg": msg, **fields}
    level_name = level.lower()
    if level_name == "exception":
        logger.exception(json.dumps(payload, default=str))
        return
    level_value = logging._nameToLevel.get(level.upper(), logging.INFO)
    logger.log(level_value, json.dumps(payload, default=str))


def log_exception(logger: logging.Logger, msg: str, **fields: Any) -> None:
    payload = {"msg": msg, **fields}
    logger.exception(json.dumps(payload, default=str))


def emit_metric(
    name: str,
    value: float = 1,
    unit: str = "Count",
    dims: Optional[Dict[str, str]] = None,
) -> None:
    dimensions = {}
    stage = os.environ.get("STAGE")
    if stage:
        dimensions["Stage"] = stage
    if dims:
        dimensions.update(dims)
    metric = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "Jarvis",
                    "Dimensions": [list(dimensions.keys())],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        **dimensions,
        name: value,
    }
    print(json.dumps(metric))


def elapsed_ms(start_time: float) -> int:
    return int((time.time() - start_time) * 1000)
