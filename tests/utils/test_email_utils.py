import pytest

from utils.email_utils import parse_raw_email


def test_parse_raw_email_plain_text():
    raw = (
        b"From: sender@example.com\r\n"
        b"To: receiver@example.com\r\n"
        b"Subject: Hello\r\n"
        b"\r\n"
        b"Plain text body."
    )

    parsed = parse_raw_email(raw)

    assert parsed["from"] == "sender@example.com"
    assert parsed["to"] == "receiver@example.com"
    assert parsed["subject"] == "Hello"
    assert "Plain text body." in parsed["text"]


def test_parse_raw_email_multipart_plain_part():
    raw = (
        b"From: sender@example.com\r\n"
        b"To: receiver@example.com\r\n"
        b"Subject: Multi\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/alternative; boundary=\"BOUNDARY\"\r\n"
        b"\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Plain part text.\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<p>HTML part</p>\r\n"
        b"--BOUNDARY--\r\n"
    )

    parsed = parse_raw_email(raw)

    assert parsed["subject"] == "Multi"
    assert "Plain part text." in parsed["text"]


def test_parse_raw_email_malformed_bytes_raises():
    with pytest.raises(AttributeError):
        parse_raw_email("not-bytes")
