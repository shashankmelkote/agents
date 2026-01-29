from types import SimpleNamespace

from utils import aws_clients


def test_get_s3_client_caches_instance(monkeypatch):
    aws_clients._S3_CLIENT = None
    created = []

    def fake_client(service_name):
        created.append(service_name)
        return SimpleNamespace(service=service_name)

    monkeypatch.setattr(aws_clients.boto3, "client", fake_client)

    first = aws_clients.get_s3_client()
    second = aws_clients.get_s3_client()

    assert first is second
    assert created == ["s3"]


def test_get_sts_client_caches_instance(monkeypatch):
    aws_clients._STS_CLIENT = None
    created = []

    def fake_client(service_name):
        created.append(service_name)
        return SimpleNamespace(service=service_name)

    monkeypatch.setattr(aws_clients.boto3, "client", fake_client)

    first = aws_clients.get_sts_client()
    second = aws_clients.get_sts_client()

    assert first is second
    assert created == ["sts"]


def test_get_secretsmanager_client_uses_config(monkeypatch):
    aws_clients._SECRETS_CLIENT = None
    captured = {}

    def fake_client(service_name, config=None):
        captured["service"] = service_name
        captured["config"] = config
        return SimpleNamespace(service=service_name, config=config)

    monkeypatch.setattr(aws_clients.boto3, "client", fake_client)

    client = aws_clients.get_secretsmanager_client()

    assert client.service == "secretsmanager"
    assert captured["service"] == "secretsmanager"
    assert captured["config"] is not None


def test_get_account_id_caches_value(monkeypatch):
    aws_clients._ACCOUNT_ID = None

    class FakeSts:
        def __init__(self):
            self.calls = 0

        def get_caller_identity(self):
            self.calls += 1
            return {"Account": "123456789012"}

    fake_sts = FakeSts()
    monkeypatch.setattr(aws_clients, "get_sts_client", lambda: fake_sts)

    first = aws_clients.get_account_id()
    second = aws_clients.get_account_id()

    assert first == "123456789012"
    assert second == "123456789012"
    assert fake_sts.calls == 1
