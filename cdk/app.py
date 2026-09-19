#!/usr/bin/env python3
"""
OmniTrace CDK application entry point.

Run with:
    cdk deploy          — deploy to the configured AWS account/region
    cdk synth           — synthesise CloudFormation template
    cdk diff            — show pending changes

Environment variables (optional overrides):
    CDK_DEFAULT_ACCOUNT — AWS account ID (falls back to constants.AWS_ACCOUNT)
    CDK_DEFAULT_REGION  — AWS region   (falls back to constants.AWS_REGION)
"""

import os

import aws_cdk as cdk

from cdk.constants import AWS_ACCOUNT, AWS_REGION, STACK_NAME
from cdk.omnitrace_stack import OmniTraceStack

app = cdk.App()

# Resolve account and region: prefer explicit CDK env vars, then constants.
account = os.environ.get("CDK_DEFAULT_ACCOUNT", AWS_ACCOUNT) or None
region = os.environ.get("CDK_DEFAULT_REGION", AWS_REGION) or None

env = cdk.Environment(account=account, region=region)

OmniTraceStack(
    app,
    STACK_NAME,
    env=env,
    description="OmniTrace — autonomous cloud incident triage and self-healing platform",
)

app.synth()
