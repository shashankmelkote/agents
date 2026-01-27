from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigateway,
    aws_lambda as _lambda,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class JarvisIngressStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        shared_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "JarvisWebhookSharedSecret",
            "jarvis/webhook/shared_secret",
        )

        router_fn = _lambda.Function(
            self,
            "RouterFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="app.handler",
            code=_lambda.Code.from_asset("lambda/router"),
        )

        authorizer_fn = _lambda.Function(
            self,
            "AuthorizerFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="app.handler",
            code=_lambda.Code.from_asset("lambda/authorizer"),
            environment={
                "SECRET_NAME": shared_secret.secret_name,
                "MAX_SKEW_SECONDS": "300",
            },
        )
        shared_secret.grant_read(authorizer_fn)

        api = apigateway.RestApi(
            self,
            "JarvisIngressApi",
            deploy_options=apigateway.StageOptions(stage_name="dev"),
            default_method_options=apigateway.MethodOptions(
                authorization_type=apigateway.AuthorizationType.NONE,
            ),
        )

        authorizer = apigateway.RequestAuthorizer(
            self,
            "JarvisRequestAuthorizer",
            handler=authorizer_fn,
            identity_sources=[
                apigateway.IdentitySource.header("x-jarvis-timestamp"),
                apigateway.IdentitySource.header("x-jarvis-signature"),
            ],
            results_cache_ttl=Duration.seconds(0),
        )

        ingress = api.root.add_resource("ingress")
        ingress.add_method(
            "POST",
            apigateway.LambdaIntegration(router_fn, proxy=True),
            authorization_type=apigateway.AuthorizationType.CUSTOM,
            authorizer=authorizer,
        )

        CfnOutput(
            self,
            "IngressUrl",
            value=f"{api.url}ingress",
        )
        CfnOutput(
            self,
            "WebhookSecretArn",
            value=shared_secret.secret_arn,
        )
