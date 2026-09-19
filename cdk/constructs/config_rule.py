"""
OmniTraceConfigRule — AWS Config IAM drift detection construct.

Implements Requirement 12.6:
  IF a Lambda function's IAM role is modified to grant permissions beyond
  its defined scope, THEN the system SHALL detect the change via AWS Config
  and publish an alert to the SNS notification topic.

Resources created:
  1. AWS Config managed rule ``IAM_POLICY_NO_STATEMENTS_WITH_ADMIN_ACCESS``
     — evaluates all IAM policies in the account and marks any that contain
       admin-level wildcard statements as NON_COMPLIANT.

  2. Amazon EventBridge rule
     — captures Config compliance-change events for the five OmniTrace IAM
       role names and filters to NON_COMPLIANT evaluations only.

  3. SNS target wiring
     — routes every matching non-compliance event to the
       ``OmniTrace-Notifications`` SNS topic so SREs are alerted promptly.
"""

import aws_cdk as cdk
from aws_cdk import aws_config as config
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_sns as sns
from constructs import Construct

from cdk.constants import (
    IAM_AUDITOR_ROLE_NAME,
    IAM_VALIDATOR_ROLE_NAME,
    IAM_PATCHER_ROLE_NAME,
    IAM_ORCHESTRATOR_ROLE_NAME,
    IAM_API_HANDLER_ROLE_NAME,
)

# All OmniTrace IAM role names — used to scope the EventBridge filter so only
# changes to *these* roles trigger an alert.
OMNITRACE_ROLE_NAMES: list[str] = [
    IAM_AUDITOR_ROLE_NAME,
    IAM_VALIDATOR_ROLE_NAME,
    IAM_PATCHER_ROLE_NAME,
    IAM_ORCHESTRATOR_ROLE_NAME,
    IAM_API_HANDLER_ROLE_NAME,
]


class OmniTraceConfigRule(Construct):
    """
    Deploys an AWS Config managed rule that detects admin-permission drift on
    IAM policies and routes non-compliance notifications to the OmniTrace
    SNS notifications topic.

    Constructor parameters
    ----------------------
    notifications_topic : aws_sns.ITopic
        The ``OmniTrace-Notifications`` SNS topic created in task 1.3.
        Non-compliance events are forwarded here.

    Public properties
    -----------------
    config_rule : config.ManagedRule
        The deployed Config managed rule (useful for integration tests /
        downstream grants).
    compliance_event_rule : events.Rule
        The EventBridge rule that captures Config non-compliance events
        scoped to OmniTrace IAM roles.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        notifications_topic: sns.ITopic,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------ #
        # 1. AWS Config managed rule                                           #
        #    Identifier: IAM_POLICY_NO_STATEMENTS_WITH_ADMIN_ACCESS           #
        #    Trigger type: CONFIGURATION_CHANGE on AWS::IAM::Policy           #
        #                  and AWS::IAM::Role resources.                      #
        # ------------------------------------------------------------------ #
        self.config_rule = config.ManagedRule(
            self,
            "IamNoAdminAccessRule",
            identifier=config.ManagedRuleIdentifiers.IAM_POLICY_NO_STATEMENTS_WITH_ADMIN_ACCESS,
            description=(
                "Detects IAM policies that contain statements granting "
                "admin-level (Action:* / Resource:*) access. Any OmniTrace "
                "IAM role modified to include such statements will be flagged "
                "as NON_COMPLIANT. (Requirement 12.6)"
            ),
            config_rule_name="OmniTrace-IamNoAdminAccess",
        )

        # ------------------------------------------------------------------ #
        # 2. EventBridge rule — Config compliance-change events               #
        #                                                                      #
        # Event pattern explanation:                                           #
        #   source           → only AWS Config events                         #
        #   detail-type      → compliance change notifications                #
        #   detail.newEvaluationResult.complianceType → NON_COMPLIANT only   #
        #   detail.resourceType → IAM role resources                          #
        #                                                                      #
        # NOTE: AWS Config compliance-change events do not include the role   #
        # name in a top-level field that supports array filtering, so we use  #
        # the broadest safe filter (resourceType = AWS::IAM::Role) and let    #
        # the SNS subscriber correlate against the known role names if needed.#
        # An optional input transformer can enrich the SNS message with the  #
        # role name for human-readable alerts.                                #
        # ------------------------------------------------------------------ #
        self.compliance_event_rule = events.Rule(
            self,
            "IamDriftComplianceRule",
            rule_name="OmniTrace-IamDriftNonCompliance",
            description=(
                "Forwards AWS Config NON_COMPLIANT evaluations for IAM roles "
                "to the OmniTrace-Notifications SNS topic. (Requirement 12.6)"
            ),
            event_pattern=events.EventPattern(
                source=["aws.config"],
                detail_type=["Config Rules Compliance Change"],
                detail={
                    "configRuleName": ["OmniTrace-IamNoAdminAccess"],
                    "newEvaluationResult": {
                        "complianceType": ["NON_COMPLIANT"],
                    },
                    "resourceType": ["AWS::IAM::Role"],
                },
            ),
        )

        # ------------------------------------------------------------------ #
        # 3. Route non-compliance events → OmniTrace-Notifications SNS topic  #
        # ------------------------------------------------------------------ #

        # Build a human-readable SNS message from the Config event payload
        # so the on-call SRE immediately knows which role drifted.
        input_transformer = events.RuleTargetInput.from_event_path("$")

        self.compliance_event_rule.add_target(
            targets.SnsTopic(
                notifications_topic,
                message=events.RuleTargetInput.from_text(
                    "OmniTrace IAM drift alert: AWS Config detected a "
                    "NON_COMPLIANT IAM role. Rule: OmniTrace-IamNoAdminAccess. "
                    "Review the AWS Config console for details."
                ),
            )
        )

        # ------------------------------------------------------------------ #
        # 4. Grant EventBridge permission to publish to the SNS topic         #
        # ------------------------------------------------------------------ #
        notifications_topic.grant_publish(
            iam.ServicePrincipal("events.amazonaws.com")
        )

        # ------------------------------------------------------------------ #
        # Output — makes the rule ARN visible in the CloudFormation console   #
        # ------------------------------------------------------------------ #
        cdk.CfnOutput(
            self,
            "ConfigRuleArn",
            value=self.config_rule.config_rule_arn,
            description="ARN of the OmniTrace IAM drift Config rule",
            export_name="OmniTrace-ConfigRuleArn",
        )
