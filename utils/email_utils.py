from email import policy
from email.utils import parseaddr
from email.parser import BytesParser
from typing import Dict


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


def parse_raw_email(raw_bytes: bytes) -> Dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    return {
        "from": message.get("From", ""),
        "to": message.get("To", ""),
        "subject": message.get("Subject", ""),
        "text": _get_email_text(message),
    }


def parse_sender_email(value: str) -> str:
    _, email = parseaddr(value)
    return email or value
