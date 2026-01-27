from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigateway,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_secretsmanager as secretsmanager,
    aws_sqs as sqs,
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

        dead_letter_queue = sqs.Queue(
            self,
            "JarvisIngressDlq",
        )
        ingress_queue = sqs.Queue(
            self,
            "JarvisIngressQueue",
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=dead_letter_queue,
            ),
        )

        router_fn = _lambda.Function(
            self,
            "RouterFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="app.handler",
            code=_lambda.Code.from_asset("lambda/router"),
            environment={"INGRESS_QUEUE_URL": ingress_queue.queue_url},
        )

        worker_fn = _lambda.Function(
            self,
            "WorkerFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="app.handler",
            code=_lambda.Code.from_asset("lambda/worker"),
        )
        worker_fn.add_event_source(
            lambda_event_sources.SqsEventSource(ingress_queue)
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

        ingress_queue.grant_send_messages(router_fn)

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
        CfnOutput(
            self,
            "IngressQueueUrl",
            value=ingress_queue.queue_url,
        )
        CfnOutput(
            self,
            "IngressQueueArn",
            value=ingress_queue.queue_arn,
        )
