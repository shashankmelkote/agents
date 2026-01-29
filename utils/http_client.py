from typing import Dict, Tuple
from urllib.request import Request, urlopen


def post_json(
    url: str,
    headers: Dict[str, str],
    body_bytes: bytes,
    timeout_seconds: int,
) -> Tuple[int, str]:
    request = Request(
        url,
        data=body_bytes,
        method="POST",
        headers=headers,
    )

    with urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read()
        response_prefix = response_body[:256].decode(errors="replace")
        return response.getcode(), response_prefix
