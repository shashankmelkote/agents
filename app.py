#!/usr/bin/env python3
import aws_cdk as cdk

from jarvis_ingress.jarvis_ingress_stack import JarvisIngressStack

app = cdk.App()
JarvisIngressStack(
    app,
    "JarvisIngressStack",
    env=cdk.Environment(region="us-east-1"),
)

app.synth()
