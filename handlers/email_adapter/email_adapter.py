import json
import logging
import os
import time
from email import policy
from email.parser import BytesParser
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote_plus, urlparse
from urllib.request import Request, urlopen

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from utils.crypto_utils import hmac_sha256_hex

ACCOUNT_ID_CACHE: Optional[str] = None
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())


def emit_metric(
    name: str,
    value: float = 1,
    unit: str = "Count",
    dims: Optional[Dict[str, str]] = None,
) -> None:
    dimensions = {"Service": "jarvis", "Component": "email_adapter"}
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


def _log_json(level: int, message: str, **fields: Any) -> None:
    payload = {"msg": message, **fields}
    LOGGER.log(level, json.dumps(payload))


def _log_exception(message: str, **fields: Any) -> None:
    payload = {"msg": message, **fields}
    LOGGER.exception(json.dumps(payload))


def _get_account_id() -> str:
    global ACCOUNT_ID_CACHE
    if ACCOUNT_ID_CACHE:
        return ACCOUNT_ID_CACHE
    sts = boto3.client("sts")
    ACCOUNT_ID_CACHE = sts.get_caller_identity()["Account"]
    return ACCOUNT_ID_CACHE


def _extract_s3_location(event: Dict[str, Any]) -> Tuple[str, str]:
    records = event.get("Records") or []
    for record in records:
        s3 = record.get("s3")
        if s3:
            bucket = s3["bucket"]["name"]
            key = s3["object"]["key"]
            return bucket, key

    raise ValueError("Expected S3 ObjectCreated event with Records[].s3 data")


def _get_email_text(message) -> str:
    if message.is_multipart():
        body = message.get_body(preferencelist=("plain",))
        if body:
            return body.get_content()
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="replace")
        return ""
    try:
        return message.get_content()
    except Exception:
        payload = message.get_payload(decode=True)
        return payload.decode(errors="replace") if payload else ""


def _parse_email(raw_email: bytes) -> Dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(raw_email)
    return {
        "from": message.get("From", ""),
        "subject": message.get("Subject", ""),
        "text": _get_email_text(message),
    }


def _build_method_arn(ingress_url: str) -> str:
    parsed = urlparse(ingress_url)
    host_parts = (parsed.hostname or "").split(".")
    api_id = host_parts[0] if host_parts else ""
    region = host_parts[2] if len(host_parts) > 2 else os.environ.get("AWS_REGION", "")
    account_id = _get_account_id()
    path_parts = (parsed.path or "").strip("/").split("/")
    stage = path_parts[0] if path_parts else ""
    resource_path = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""
    return (
        f"arn:aws:execute-api:{region}:{account_id}:{api_id}"
        f"/{stage}/POST/{resource_path}"
    )


def _fetch_secret(
    secret_name: str,
    aws_request_id: str,
) -> str:
    config = Config(
        connect_timeout=2,
        read_timeout=3,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    client = boto3.client("secretsmanager", config=config)
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
        duration_ms = int((time.time() - secret_start) * 1000)
        emit_metric("SecretFetchFailure", 1)
        emit_metric("SecretFetchDurationMs", duration_ms, "Milliseconds")
        _log_json(
            logging.WARNING,
            "email_adapter_secret_fetch_fail",
            aws_request_id=aws_request_id,
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
        duration_ms = int((time.time() - secret_start) * 1000)
        emit_metric("SecretFetchFailure", 1)
        emit_metric("SecretFetchDurationMs", duration_ms, "Milliseconds")
        _log_json(
            logging.WARNING,
            "email_adapter_secret_fetch_fail",
            aws_request_id=aws_request_id,
            secret_name=secret_name,
            duration_ms=duration_ms,
            error_type="ValueError",
            error_message="SecretString is empty",
            aws_error_code="",
            aws_error_message="",
        )
        raise ValueError("SecretString is empty")
    duration_ms = int((time.time() - secret_start) * 1000)
    emit_metric("SecretFetchSuccess", 1)
    emit_metric("SecretFetchDurationMs", duration_ms, "Milliseconds")
    _log_json(
        logging.INFO,
        "email_adapter_secret_fetch_ok",
        aws_request_id=aws_request_id,
        secret_name=secret_name,
        duration_ms=duration_ms,
    )
    return secret_value


def _post_ingress(
    payload: Dict[str, Any],
    ingress_url: str,
    secret: str,
    timeout_seconds: int,
) -> Tuple[int, str]:
    timestamp = str(int(time.time()))
    body = json.dumps(payload, separators=(",", ":"))
    method_arn = _build_method_arn(ingress_url)
    signature = hmac_sha256_hex(secret, f"{timestamp}.{method_arn}")

    request = Request(
        ingress_url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-jarvis-timestamp": timestamp,
            "x-jarvis-signature": signature,
        },
    )

    with urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read()
        response_prefix = response_body[:256].decode(errors="replace")
        return response.getcode(), response_prefix


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    start_time = time.time()
    aws_request_id = getattr(context, "aws_request_id", "")
    bucket = ""
    decoded_key = ""
    message_id = ""
    error_logged = False
    emit_metric("EmailsReceived", 1)
    _log_json(
        logging.INFO,
        "email_adapter_start",
        aws_request_id=aws_request_id,
        bucket=bucket,
        key=decoded_key,
        message_id=message_id,
        duration_ms=0,
    )
    try:
        bucket, key = _extract_s3_location(event)
        decoded_key = unquote_plus(key)
        message_id = os.path.basename(decoded_key) if decoded_key else ""
        _log_json(
            logging.INFO,
            "email_adapter_s3_location",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )

        s3_client = boto3.client("s3")
        try:
            response = s3_client.get_object(Bucket=bucket, Key=decoded_key)
            raw_email = response["Body"].read()
        except Exception as exc:
            emit_metric("S3ReadFailure", 1)
            _log_exception(
                "email_adapter_error",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            error_logged = True
            raise
        emit_metric("S3ReadSuccess", 1)
        _log_json(
            logging.INFO,
            "email_adapter_s3_read_ok",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )

        try:
            parsed_email = _parse_email(raw_email)
        except Exception as exc:
            emit_metric("ParseFailure", 1)
            _log_exception(
                "email_adapter_error",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            error_logged = True
            raise
        emit_metric("ParseSuccess", 1)
        _log_json(
            logging.INFO,
            "email_adapter_parse_ok",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )

        has_secret_name_env = bool(os.environ.get("SECRET_NAME"))
        has_ingress_url_env = bool(os.environ.get("INGRESS_URL"))
        _log_json(
            logging.INFO,
            "email_adapter_config_loaded",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
            has_secret_name_env=has_secret_name_env,
            has_ingress_url_env=has_ingress_url_env,
        )

        payload = {
            "source": "email",
            "from": parsed_email["from"],
            "subject": parsed_email["subject"],
            "text": parsed_email["text"],
            "s3": {"bucket": bucket, "key": decoded_key},
        }

        try:
            secret_name = os.environ["SECRET_NAME"]
            ingress_url = os.environ["INGRESS_URL"]
            if not secret_name:
                raise ValueError("SECRET_NAME is empty")
            if not ingress_url:
                raise ValueError("INGRESS_URL is empty")
        except (KeyError, ValueError) as exc:
            emit_metric("ConfigError", 1)
            _log_exception(
                "email_adapter_error",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            error_logged = True
            raise

        remaining_ms = getattr(context, "get_remaining_time_in_millis", lambda: 10000)()
        if remaining_ms < 4000:
            _log_json(
                logging.WARNING,
                "email_adapter_abort_low_time",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                remaining_ms=remaining_ms,
            )
            raise RuntimeError("Aborting secret fetch due to low remaining time")

        # TODO: If Lambda runs in a VPC, ensure NAT or a VPC interface endpoint for
        # Secrets Manager; otherwise calls may hang.
        shared_secret = _fetch_secret(secret_name, aws_request_id)

        publish_start = time.time()
        ingress_host = urlparse(ingress_url).hostname or ""
        _log_json(
            logging.INFO,
            "email_adapter_publish_start",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((publish_start - start_time) * 1000),
            ingress_host=ingress_host,
        )
        remaining_ms = getattr(context, "get_remaining_time_in_millis", lambda: 10000)()
        timeout_seconds = min(10, max(1, remaining_ms // 1000 - 1))
        publish_failure_emitted = False
        try:
            status_code, response_prefix = _post_ingress(
                payload, ingress_url, shared_secret, timeout_seconds
            )
            _log_json(
                logging.INFO,
                "email_adapter_publish_response",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - publish_start) * 1000),
                status_code=status_code,
                response_body_prefix=response_prefix,
            )
            if not 200 <= status_code < 300:
                emit_metric("IngressResponseNon2xx", 1)
                emit_metric("IngressPublishFailure", 1)
                publish_failure_emitted = True
                raise RuntimeError(f"Ingress responded with status {status_code}")
        except Exception as exc:
            if not publish_failure_emitted:
                emit_metric("IngressPublishFailure", 1)
            _log_exception(
                "email_adapter_error",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            error_logged = True
            raise
        emit_metric("IngressPublishSuccess", 1)
        _log_json(
            logging.INFO,
            "email_adapter_publish_ok",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        _log_json(
            logging.INFO,
            "email_adapter_done",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        return {"statusCode": 200, "body": json.dumps({"status": "ok"})}
    except Exception as exc:
        if not error_logged:
            _log_exception(
                "email_adapter_error",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        raise
    finally:
        emit_metric("DurationMs", int((time.time() - start_time) * 1000), "Milliseconds")
