import json
import os
import time
from typing import Any, Dict, Tuple
from urllib.parse import unquote_plus, urlparse

from utils.apigw import build_method_arn_for_ingress
from utils.aws_clients import get_account_id, get_s3_client
from utils.crypto_utils import hmac_sha256_hex
from utils.email_utils import parse_raw_email
from utils.http_client import post_json
from utils.lambda_time import http_timeout_seconds, remaining_ms
from utils.observability import emit_metric, get_logger, log_exception, log_json
from utils.s3_events import extract_s3_location_from_event, infer_message_id_from_key
from utils.secrets import configure_secret_cache, get_secret_cached

LOGGER = get_logger(__name__)
METRIC_DIMS = {"Service": "jarvis", "Component": "email_adapter"}


def emit_email_metric(
    name: str,
    value: float = 1,
    unit: str = "Count",
) -> None:
    emit_metric(name, value, unit, dims=METRIC_DIMS)


def _ingress_region(ingress_url: str) -> str:
    parsed = urlparse(ingress_url)
    host_parts = (parsed.hostname or "").split(".")
    parsed_region = host_parts[2] if len(host_parts) > 2 else ""
    return parsed_region or os.environ.get("AWS_REGION", "")


def _ingress_stage_and_resource(ingress_url: str) -> Tuple[str, str]:
    parsed = urlparse(ingress_url)
    path_parts = (parsed.path or "").strip("/").split("/")
    stage = os.environ.get("STAGE") or (path_parts[0] if path_parts else "")
    resource_path = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""
    return stage, resource_path


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    start_time = time.time()
    aws_request_id = getattr(context, "aws_request_id", "")
    bucket = ""
    decoded_key = ""
    message_id = ""
    error_logged = False
    emit_email_metric("EmailsReceived", 1)
    log_json(
        LOGGER,
        "info",
        "email_adapter_start",
        aws_request_id=aws_request_id,
        bucket=bucket,
        key=decoded_key,
        message_id=message_id,
        duration_ms=0,
    )
    try:
        bucket, key = extract_s3_location_from_event(event)
        decoded_key = unquote_plus(key)
        message_id = infer_message_id_from_key(decoded_key)
        log_json(
            LOGGER,
            "info",
            "email_adapter_s3_location",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )

        s3_client = get_s3_client()
        try:
            response = s3_client.get_object(Bucket=bucket, Key=decoded_key)
            raw_email = response["Body"].read()
        except Exception as exc:
            emit_email_metric("S3ReadFailure", 1)
            log_exception(
                LOGGER,
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
        emit_email_metric("S3ReadSuccess", 1)
        log_json(
            LOGGER,
            "info",
            "email_adapter_s3_read_ok",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )

        try:
            parsed_email = parse_raw_email(raw_email)
        except Exception as exc:
            emit_email_metric("ParseFailure", 1)
            log_exception(
                LOGGER,
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
        emit_email_metric("ParseSuccess", 1)
        log_json(
            LOGGER,
            "info",
            "email_adapter_parse_ok",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )

        has_secret_name_env = bool(os.environ.get("SECRET_NAME"))
        has_ingress_url_env = bool(os.environ.get("INGRESS_URL"))
        log_json(
            LOGGER,
            "info",
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
            emit_email_metric("ConfigError", 1)
            log_exception(
                LOGGER,
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

        rem_ms = remaining_ms(context)
        if rem_ms < 4000:
            log_json(
                LOGGER,
                "warning",
                "email_adapter_abort_low_time",
                aws_request_id=aws_request_id,
                bucket=bucket,
                key=decoded_key,
                message_id=message_id,
                duration_ms=int((time.time() - start_time) * 1000),
                remaining_ms=rem_ms,
            )
            raise RuntimeError("Aborting secret fetch due to low remaining time")

        # TODO: If Lambda runs in a VPC, ensure NAT or a VPC interface endpoint for
        # Secrets Manager; otherwise calls may hang.
        configure_secret_cache(
            logger=LOGGER,
            metric_dims=METRIC_DIMS,
            aws_request_id=aws_request_id,
        )
        shared_secret = get_secret_cached(secret_name)

        publish_start = time.time()
        ingress_host = urlparse(ingress_url).hostname or ""
        log_json(
            LOGGER,
            "info",
            "email_adapter_publish_start",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((publish_start - start_time) * 1000),
            ingress_host=ingress_host,
        )
        timeout_seconds = http_timeout_seconds(context, cap=10, reserve_s=1, floor=1)
        publish_failure_emitted = False
        try:
            timestamp = str(int(time.time()))
            region = _ingress_region(ingress_url)
            stage, resource_path = _ingress_stage_and_resource(ingress_url)
            method_arn = build_method_arn_for_ingress(
                ingress_url,
                region=region,
                account_id=get_account_id(),
                stage=stage,
                http_method="POST",
                resource_path=f"/{resource_path}" if resource_path else "",
            )
            signature = hmac_sha256_hex(shared_secret, f"{timestamp}.{method_arn}")
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            status_code, response_prefix = post_json(
                ingress_url,
                headers={
                    "Content-Type": "application/json",
                    "x-jarvis-timestamp": timestamp,
                    "x-jarvis-signature": signature,
                },
                body_bytes=body,
                timeout_seconds=timeout_seconds,
            )
            log_json(
                LOGGER,
                "info",
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
                emit_email_metric("IngressResponseNon2xx", 1)
                emit_email_metric("IngressPublishFailure", 1)
                publish_failure_emitted = True
                raise RuntimeError(f"Ingress responded with status {status_code}")
        except Exception as exc:
            if not publish_failure_emitted:
                emit_email_metric("IngressPublishFailure", 1)
            log_exception(
                LOGGER,
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
        emit_email_metric("IngressPublishSuccess", 1)
        log_json(
            LOGGER,
            "info",
            "email_adapter_publish_ok",
            aws_request_id=aws_request_id,
            bucket=bucket,
            key=decoded_key,
            message_id=message_id,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        log_json(
            LOGGER,
            "info",
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
            log_exception(
                LOGGER,
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
        emit_email_metric("DurationMs", int((time.time() - start_time) * 1000), "Milliseconds")
