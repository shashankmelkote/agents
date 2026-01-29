import os
import sys
import types


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


try:
    import boto3  # noqa: F401
except ModuleNotFoundError:
    boto3_stub = types.ModuleType("boto3")

    def _missing_client(*args, **kwargs):
        raise ModuleNotFoundError("boto3 is not installed")

    boto3_stub.client = _missing_client
    sys.modules["boto3"] = boto3_stub


try:
    import botocore.exceptions  # noqa: F401
    import botocore.config  # noqa: F401
except ModuleNotFoundError:
    botocore_stub = types.ModuleType("botocore")
    exceptions_stub = types.ModuleType("botocore.exceptions")
    config_stub = types.ModuleType("botocore.config")

    class ClientError(Exception):
        def __init__(self, response, operation_name):
            super().__init__(response.get("Error", {}).get("Message", "ClientError"))
            self.response = response
            self.operation_name = operation_name

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    exceptions_stub.ClientError = ClientError
    config_stub.Config = Config
    botocore_stub.exceptions = exceptions_stub
    botocore_stub.config = config_stub
    sys.modules["botocore"] = botocore_stub
    sys.modules["botocore.exceptions"] = exceptions_stub
    sys.modules["botocore.config"] = config_stub
