"""
OmniTraceStack — top-level CDK stack for the OmniTrace platform.

This module defines the OmniTraceStack class.  All AWS resources (DynamoDB,
SNS, SQS, EventBridge, Step Functions, Lambda, API Gateway, Amplify,
CloudWatch, IAM, Config) are instantiated inside this single stack to keep
cross-resource references straightforward and avoid cross-stack dependency
cycles at this stage of the project.

Each logical grouping of resources will be extracted into dedicated nested
constructs (or separate stacks) as the project matures.
"""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from cdk.constants import (
    STACK_NAME,
    RESOURCE_TAGS,
    DYNAMODB_TABLE_NAME,
    DYNAMODB_PK_NAME,
    DYNAMODB_SK_NAME,
    DYNAMODB_TTL_ATTRIBUTE,
    SNS_NOTIFICATIONS_TOPIC_NAME,
    SNS_SRE_ESCALATION_TOPIC_NAME,
    SQS_DLQ_NAME,
)
from cdk.constructs.iam_roles import OmniTraceIamRoles
from cdk.constructs.eventbridge_rule import OmniTraceEventBridgeRule


class OmniTraceStack(cdk.Stack):
    """
    The single CDK stack for the entire OmniTrace platform.

    Resources are added incrementally by subsequent tasks.  This class
    provides the base stack shell that all other constructs will be
    attached to.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str = STACK_NAME,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Apply project-wide tags to every resource in this stack.
        for key, value in RESOURCE_TAGS.items():
            cdk.Tags.of(self).add(key, value)

        # ------------------------------------------------------------------ #
        # Task 1.2 — DynamoDB table                                           #
        # ------------------------------------------------------------------ #
        self.table = dynamodb.Table(
            self,
            "OmniTraceIncidentsTable",
            table_name=DYNAMODB_TABLE_NAME,
            partition_key=dynamodb.Attribute(
                name=DYNAMODB_PK_NAME,
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name=DYNAMODB_SK_NAME,
                type=dynamodb.AttributeType.STRING,
            ),
            point_in_time_recovery=True,
            time_to_live_attribute=DYNAMODB_TTL_ATTRIBUTE,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ------------------------------------------------------------------ #
        # Task 1.3 — SNS topics + SQS dead-letter queue                      #
        # ------------------------------------------------------------------ #

        # General notification topic — used for resolution alerts, failure
        # notifications, and CloudWatch alarm actions (Requirements 2.4, 11.3).
        self.notifications_topic = sns.Topic(
            self,
            "OmniTraceNotificationsTopic",
            topic_name=SNS_NOTIFICATIONS_TOPIC_NAME,
            display_name="OmniTrace General Notifications",
        )

        # SRE escalation topic — used by Patcher HIGH-risk path and Config
        # rule non-compliance notifications (Requirements 5.4, 7.1, 7.4).
        self.sre_escalation_topic = sns.Topic(
            self,
            "OmniTraceSREEscalationTopic",
            topic_name=SNS_SRE_ESCALATION_TOPIC_NAME,
            display_name="OmniTrace SRE Escalation",
        )

        # Dead-letter queue for EventBridge rule — captures events that fail
        # schema validation or cannot be delivered to the state machine
        # (Requirements 1.3, 1.4).
        self.eventbridge_dlq = sqs.Queue(
            self,
            "OmniTraceEventBridgeDLQ",
            queue_name=SQS_DLQ_NAME,
            retention_period=cdk.Duration.days(14),
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ------------------------------------------------------------------ #
        # Task 1.4 — EventBridge rule with DLQ                               #
        # ------------------------------------------------------------------ #
        # Matches source="omnitrace.simulator" + detail-type="OmniTraceIncident".
        # The DLQ (self.eventbridge_dlq) is stored on the construct so task
        # 5.2 can attach it to the Step Functions target via
        # dead_letter_queue parameter.  The rule itself is exposed as
        # self.incident_rule for task 5.2 to add the SFN target.
        _eventbridge = OmniTraceEventBridgeRule(
            self,
            "OmniTraceEventBridgeRule",
            dlq=self.eventbridge_dlq,
        )
        self.incident_rule = _eventbridge.incident_rule

        # ------------------------------------------------------------------ #
        # Resource placeholders — populated by subsequent tasks               #
        # ------------------------------------------------------------------ #
        # Task 1.5  → IAM roles  ← implemented below
        # Task 1.6  → AWS Config rule
        # Task 4.4  → Simulator Lambda
        # Task 5.2  → Step Functions state machine (wires target to incident_rule)
        # Task 6.4  → Auditor Lambda
        # Task 7.3  → Validator Lambda
        # Task 8.6  → Patcher Lambda
        # Task 10.6 → API Gateway
        # Task 12.11→ Amplify hosting
        # Task 14.1 → CloudWatch alarm
        # Task 14.2 → CloudWatch log groups
        # ------------------------------------------------------------------ #

        # ------------------------------------------------------------------ #
        # Task 1.5 — Least-privilege IAM roles for all Lambda functions       #
        # ------------------------------------------------------------------ #
        self.iam_roles = OmniTraceIamRoles(self, "OmniTraceIamRoles")
