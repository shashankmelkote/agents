from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_ses as ses,
    aws_ses_actions as ses_actions,
    aws_secretsmanager as secretsmanager,
    aws_sqs as sqs,
    custom_resources as cr,
)
from constructs import Construct


class JarvisIngressStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        inbound_email_domain = (
            self.node.try_get_context("inboundEmailDomain")
            or "jarvisassistants.ai"
        )
        jarvis_local_part = (
            self.node.try_get_context("jarvisLocalPart") or "jarvis"
        )
        jarvis_domain = self.node.try_get_context("jarvisDomain") or inbound_email_domain
        jarvis_email = f"{jarvis_local_part}@{inbound_email_domain}"
        ses_receipt_rule_set_name = (
            self.node.try_get_context("sesReceiptRuleSetName")
            or "jarvis-inbound-rules"
        )
        shared_secret_name = (
            self.node.try_get_context("sharedSecretName")
            or "jarvis/webhook/shared_secret"
        )
        account_id = Stack.of(self).account

        shared_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "JarvisWebhookSharedSecret",
            shared_secret_name,
        )

        inbound_email_bucket = s3.Bucket(
            self,
            "JarvisInboundEmailBucket",
        )
        inbound_email_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("ses.amazonaws.com")],
                actions=["s3:PutObject"],
                resources=[f"{inbound_email_bucket.bucket_arn}/ses-inbound/*"],
                conditions={"StringEquals": {"aws:SourceAccount": account_id}},
            )
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
        inbound_email_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(ingress_queue),
            s3.NotificationKeyFilter(prefix="ingress-queue/"),
        )
        ingress_queue.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal("s3.amazonaws.com")],
                actions=["sqs:SendMessage"],
                resources=[ingress_queue.queue_arn],
                conditions={
                    "ArnLike": {"aws:SourceArn": inbound_email_bucket.bucket_arn},
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            )
        )

        router_fn = _lambda.Function(
            self,
            "RouterFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="router.ingress_router.handler",
            code=_lambda.Code.from_asset("handlers"),
            environment={"INGRESS_QUEUE_URL": ingress_queue.queue_url},
        )

        worker_fn = _lambda.Function(
            self,
            "WorkerFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="worker.sqs_worker.handler",
            code=_lambda.Code.from_asset("handlers"),
        )
        worker_fn.add_event_source(
            lambda_event_sources.SqsEventSource(ingress_queue)
        )

        authorizer_fn = _lambda.Function(
            self,
            "AuthorizerFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="authorizer.authorizer.handler",
            code=_lambda.Code.from_asset("handlers"),
            environment={
                "SECRET_NAME": shared_secret_name,
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

        email_adapter_fn = _lambda.Function(
            self,
            "EmailAdapterFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="email_adapter.email_adapter.handler",
            code=_lambda.Code.from_asset("handlers"),
            environment={
                "INGRESS_URL": f"{api.url}ingress",
                "SECRET_NAME": shared_secret_name,
            },
        )
        inbound_email_bucket.grant_read(email_adapter_fn)
        shared_secret.grant_read(email_adapter_fn)
        inbound_email_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(email_adapter_fn),
            s3.NotificationKeyFilter(prefix="ses-inbound/"),
        )
        email_adapter_fn.add_permission(
            "AllowS3Invoke",
            principal=iam.ServicePrincipal("s3.amazonaws.com"),
            action="lambda:InvokeFunction",
            source_account=account_id,
            source_arn=inbound_email_bucket.bucket_arn,
        )

        receipt_rule_set = ses.ReceiptRuleSet(
            self,
            "JarvisInboundReceiptRuleSet",
            receipt_rule_set_name=ses_receipt_rule_set_name,
        )
        receipt_rule_set.add_rule(
            "JarvisInboundEmailRule",
            recipients=[jarvis_email],
            actions=[
                ses_actions.S3(
                    bucket=inbound_email_bucket,
                    object_key_prefix="ses-inbound/",
                ),
            ],
        )
        ses_activation = cr.AwsCustomResource(
            self,
            "ActivateSesReceiptRuleSet",
            on_create=cr.AwsSdkCall(
                service="SES",
                action="setActiveReceiptRuleSet",
                parameters={"RuleSetName": ses_receipt_rule_set_name},
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"activate-ses-ruleset-{ses_receipt_rule_set_name}"
                ),
            ),
            on_update=cr.AwsSdkCall(
                service="SES",
                action="setActiveReceiptRuleSet",
                parameters={"RuleSetName": ses_receipt_rule_set_name},
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"activate-ses-ruleset-{ses_receipt_rule_set_name}"
                ),
            ),
            policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE
            ),
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        ses_activation.node.add_dependency(receipt_rule_set)

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
        CfnOutput(
            self,
            "JarvisDomain",
            value=jarvis_domain,
        )
        CfnOutput(
            self,
            "JarvisEmail",
            value=jarvis_email,
        )
        CfnOutput(
            self,
            "InboundReceiptRuleSetName",
            value=receipt_rule_set.receipt_rule_set_name,
        )
        CfnOutput(
            self,
            "InboundRecipientEmail",
            value=jarvis_email,
        )
        CfnOutput(
            self,
            "InboundEmailBucketName",
            value=inbound_email_bucket.bucket_name,
        )
