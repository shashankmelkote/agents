import boto3
import hashlib
import hmac
from typing import Dict

SECRET_CACHE: Dict[str, str] = {}


def get_secret(secret_name: str) -> str:
    """Fetch a string secret value from AWS Secrets Manager."""
    if secret_name in SECRET_CACHE:
        return SECRET_CACHE[secret_name]
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    secret_value = response.get("SecretString")
    if not secret_value:
        raise ValueError("SecretString is empty")
    SECRET_CACHE[secret_name] = secret_value
    return secret_value


def hmac_sha256_hex(key: str, message: str) -> str:
    """Compute HMAC-SHA256 in lowercase hexadecimal format."""
    return hmac.new(
        key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().lower()
