from utils.apigw import build_method_arn_for_ingress


def test_build_method_arn_for_ingress():
    arn = build_method_arn_for_ingress(
        "https://abc123.execute-api.us-east-1.amazonaws.com/dev/ingress",
        region="us-east-1",
        account_id="123456789012",
        stage="dev",
        http_method="POST",
        resource_path="/ingress",
    )

    assert (
        arn
        == "arn:aws:execute-api:us-east-1:123456789012:abc123/dev/POST/ingress"
    )
