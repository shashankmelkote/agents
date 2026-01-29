import time
from typing import Any, Dict, Optional, Tuple

from botocore.exceptions import ClientError

from utils.aws_clients import get_secretsmanager_client
from utils.observability import emit_metric, elapsed_ms, get_logger, log_json

_SECRET_CACHE: Dict[str, Tuple[str, float]] = {}
_SECRET_LOGGER = None
_SECRET_COMMON_FIELDS: Dict[str, Any] = {}
_SECRET_METRIC_DIMS: Optional[Dict[str, str]] = None


def configure_secret_cache(
    *,
    logger=None,
    metric_dims: Optional[Dict[str, str]] = None,
    **common_fields: Any,
) -> None:
    global _SECRET_LOGGER
    global _SECRET_COMMON_FIELDS
    global _SECRET_METRIC_DIMS
    _SECRET_LOGGER = logger
    _SECRET_COMMON_FIELDS = dict(common_fields)
    _SECRET_METRIC_DIMS = metric_dims


def _metric(name: str, value: float = 1, unit: str = "Count") -> None:
    emit_metric(name, value, unit, dims=_SECRET_METRIC_DIMS)


def _logger():
    return _SECRET_LOGGER or get_logger(__name__)


def _log(message: str, **fields: Any) -> None:
    log_json(_logger(), "info", message, **_SECRET_COMMON_FIELDS, **fields)


def _log_warning(message: str, **fields: Any) -> None:
    log_json(_logger(), "warning", message, **_SECRET_COMMON_FIELDS, **fields)


def _fetch_secret(secret_name: str) -> str:
    client = get_secretsmanager_client()
    secret_start = time.time()
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except Exception as exc:
        error_code = ""
        error_message = ""
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            error_code = error.get("Code", "")
            error_message = error.get("Message", "")
        duration_ms = elapsed_ms(secret_start)
        _metric("SecretFetchFailure", 1)
        _metric("SecretFetchDurationMs", duration_ms, "Milliseconds")
        _log_warning(
            "email_adapter_secret_fetch_fail",
            secret_name=secret_name,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=str(exc),
            aws_error_code=error_code,
            aws_error_message=error_message,
        )
        raise
    secret_value = response.get("SecretString")
    if not secret_value:
        duration_ms = elapsed_ms(secret_start)
        _metric("SecretFetchFailure", 1)
        _metric("SecretFetchDurationMs", duration_ms, "Milliseconds")
        _log_warning(
            "email_adapter_secret_fetch_fail",
            secret_name=secret_name,
            duration_ms=duration_ms,
            error_type="ValueError",
            error_message="SecretString is empty",
            aws_error_code="",
            aws_error_message="",
        )
        raise ValueError("SecretString is empty")
    duration_ms = elapsed_ms(secret_start)
    _metric("SecretFetchSuccess", 1)
    _metric("SecretFetchDurationMs", duration_ms, "Milliseconds")
    _log(
        "email_adapter_secret_fetch_ok",
        secret_name=secret_name,
        duration_ms=duration_ms,
    )
    return secret_value


def get_secret_cached(secret_name: str, *, ttl_seconds: int = 900) -> str:
    now = time.time()
    cache_entry = _SECRET_CACHE.get(secret_name)
    if cache_entry:
        cached_value, cached_at = cache_entry
        cache_age = now - cached_at
        if cache_age < ttl_seconds:
            duration_ms = int((time.time() - now) * 1000)
            _log(
                "email_adapter_secret_cache_hit",
                secret_name=secret_name,
                duration_ms=duration_ms,
                cache_age_ms=int(cache_age * 1000),
            )
            return cached_value

    cache_age_ms = None
    if cache_entry:
        cache_age_ms = int((now - cache_entry[1]) * 1000)
    miss_start = time.time()
    secret_value = _fetch_secret(secret_name)
    fetched_at = time.time()
    _SECRET_CACHE[secret_name] = (secret_value, fetched_at)
    duration_ms = int((fetched_at - miss_start) * 1000)
    _log(
        "email_adapter_secret_cache_miss",
        secret_name=secret_name,
        duration_ms=duration_ms,
        cache_age_ms=cache_age_ms,
    )
    return secret_value
