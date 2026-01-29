from utils.email_utils import parse_sender_email


def test_parse_sender_email_with_name():
    assert parse_sender_email("\"Name\" <user@example.com>") == "user@example.com"


def test_parse_sender_email_without_name():
    assert parse_sender_email("user@example.com") == "user@example.com"
