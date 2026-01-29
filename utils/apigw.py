from urllib.parse import urlparse


def build_method_arn_for_ingress(
    ingress_url: str,
    *,
    region: str,
    account_id: str,
    stage: str,
    http_method: str = "POST",
    resource_path: str = "/ingress",
) -> str:
    parsed = urlparse(ingress_url)
    host_parts = (parsed.hostname or "").split(".")
    api_id = host_parts[0] if host_parts else ""
    resource = resource_path.lstrip("/")
    return (
        f"arn:aws:execute-api:{region}:{account_id}:{api_id}"
        f"/{stage}/{http_method}/{resource}"
    )
