import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from jarvis_ingress.jarvis_ingress_stack import JarvisIngressStack


def test_stack_resources():
    shared_secret_name = "jarvis/webhook/shared_secret"
    app = cdk.App()
    stack = JarvisIngressStack(
        app,
        "JarvisIngressStack",
        env=cdk.Environment(region="us-east-1"),
    )
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::Lambda::Function", 2)
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    template.resource_count_is("AWS::ApiGateway::Authorizer", 1)
    template.resource_count_is("AWS::SecretsManager::Secret", 1)

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.11",
        },
    )

    template.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {
            "Name": shared_secret_name,
        },
    )

    template.has_resource_properties(
        "AWS::ApiGateway::Stage",
        {
            "StageName": "dev",
        },
    )

    template.has_resource_properties(
        "AWS::ApiGateway::Method",
        {
            "AuthorizationType": "CUSTOM",
            "HttpMethod": "POST",
        },
    )

    template.has_output(
        "IngressUrl",
        {
            "Value": Match.any_value(),
        },
    )
    template.has_output(
        "WebhookSecretArn",
        {
            "Value": Match.any_value(),
        },
    )
