from typing import Optional

import boto3
from botocore.config import Config

_S3_CLIENT = None
_STS_CLIENT = None
_SECRETS_CLIENT = None
_ACCOUNT_ID: Optional[str] = None


def get_s3_client():
    global _S3_CLIENT
    if _S3_CLIENT is None:
        _S3_CLIENT = boto3.client("s3")
    return _S3_CLIENT


def get_sts_client():
    global _STS_CLIENT
    if _STS_CLIENT is None:
        _STS_CLIENT = boto3.client("sts")
    return _STS_CLIENT


def get_secretsmanager_client():
    global _SECRETS_CLIENT
    if _SECRETS_CLIENT is None:
        config = Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"max_attempts": 2, "mode": "standard"},
        )
        _SECRETS_CLIENT = boto3.client("secretsmanager", config=config)
    return _SECRETS_CLIENT


def get_account_id() -> str:
    global _ACCOUNT_ID
    if _ACCOUNT_ID:
        return _ACCOUNT_ID
    sts = get_sts_client()
    _ACCOUNT_ID = sts.get_caller_identity()["Account"]
    return _ACCOUNT_ID
