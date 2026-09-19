"""
OmniTraceIamRoles — least-privilege IAM roles for all OmniTrace Lambda functions.

Each role:
  - Trusts only lambda.amazonaws.com
  - Grants exactly the permissions required by the corresponding agent/handler
  - Scopes Bedrock model ARNs to the specific model IDs defined in constants
  - Attaches AWSLambdaBasicExecutionRole so Lambda can write CloudWatch Logs

Roles defined:
  OmniTrace-Auditor-Role    → Auditor Lambda
  OmniTrace-Validator-Role  → Validator Lambda
  OmniTrace-Patcher-Role    → Patcher Lambda
  OmniTrace-APIHandler-Role → API Gateway Lambda handlers
  OmniTrace-Orchestrator-Role → Step Functions Orchestrator Lambda (if needed)
"""

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

from cdk.constants import (
    IAM_AUDITOR_ROLE_NAME,
    IAM_VALIDATOR_ROLE_NAME,
    IAM_PATCHER_ROLE_NAME,
    IAM_ORCHESTRATOR_ROLE_NAME,
    IAM_API_HANDLER_ROLE_NAME,
    BEDROCK_AUDITOR_MODEL_ID,
    BEDROCK_VALIDATOR_MODEL_ID,
    BEDROCK_PATCHER_MODEL_ID,
    DYNAMODB_TABLE_NAME,
    SNS_NOTIFICATIONS_TOPIC_NAME,
    SNS_SRE_ESCALATION_TOPIC_NAME,
    LAMBDA_AUDITOR_NAME,
    LAMBDA_VALIDATOR_NAME,
    LAMBDA_PATCHER_NAME,
)


class OmniTraceIamRoles(Construct):
    """
    Defines all five least-privilege IAM roles used by OmniTrace Lambda functions.

    Exposes each role as a public property so the parent stack (and other
    constructs) can reference them when creating Lambda functions.

    Properties:
        auditor_role      — OmniTrace-Auditor-Role
        validator_role    — OmniTrace-Validator-Role
        patcher_role      — OmniTrace-Patcher-Role
        api_handler_role  — OmniTrace-APIHandler-Role
        orchestrator_role — OmniTrace-Orchestrator-Role
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Shared trust policy: all roles are assumed by Lambda
        lambda_principal = iam.ServicePrincipal("lambda.amazonaws.com")

        # Shared managed policy: allows Lambda to write logs to CloudWatch
        lambda_basic_execution = iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole"
        )

        # Resolve the current partition and region from the stack for ARN construction
        partition = cdk.Stack.of(self).partition
        region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        # ------------------------------------------------------------------ #
        # Bedrock model ARNs (scoped to specific model IDs)                   #
        # ------------------------------------------------------------------ #
        bedrock_auditor_model_arn = (
            f"arn:{partition}:bedrock:{region}::foundation-model/{BEDROCK_AUDITOR_MODEL_ID}"
        )
        # nova-pro is shared by Validator and Patcher
        bedrock_nova_model_arn = (
            f"arn:{partition}:bedrock:{region}::foundation-model/{BEDROCK_VALIDATOR_MODEL_ID}"
        )

        # ------------------------------------------------------------------ #
        # DynamoDB table ARN                                                   #
        # ------------------------------------------------------------------ #
        dynamodb_table_arn = (
            f"arn:{partition}:dynamodb:{region}:{account}:table/{DYNAMODB_TABLE_NAME}"
        )

        # ------------------------------------------------------------------ #
        # SNS topic ARNs                                                       #
        # ------------------------------------------------------------------ #
        sns_notifications_arn = (
            f"arn:{partition}:sns:{region}:{account}:{SNS_NOTIFICATIONS_TOPIC_NAME}"
        )
        sns_sre_escalation_arn = (
            f"arn:{partition}:sns:{region}:{account}:{SNS_SRE_ESCALATION_TOPIC_NAME}"
        )

        # ------------------------------------------------------------------ #
        # Agent Lambda ARNs (used by Orchestrator role)                        #
        # ------------------------------------------------------------------ #
        auditor_lambda_arn = (
            f"arn:{partition}:lambda:{region}:{account}:function:{LAMBDA_AUDITOR_NAME}"
        )
        validator_lambda_arn = (
            f"arn:{partition}:lambda:{region}:{account}:function:{LAMBDA_VALIDATOR_NAME}"
        )
        patcher_lambda_arn = (
            f"arn:{partition}:lambda:{region}:{account}:function:{LAMBDA_PATCHER_NAME}"
        )

        # ------------------------------------------------------------------ #
        # 1. OmniTrace-Auditor-Role                                            #
        #    Permissions: CloudWatch Logs read + Bedrock claude-3-5-sonnet     #
        # ------------------------------------------------------------------ #
        self.auditor_role = iam.Role(
            self,
            "AuditorRole",
            role_name=IAM_AUDITOR_ROLE_NAME,
            assumed_by=lambda_principal,
            managed_policies=[lambda_basic_execution],
            description=(
                "Least-privilege role for OmniTrace Auditor Lambda. "
                "Allows CloudWatch Logs reads and Bedrock claude-3-5-sonnet invocation."
            ),
        )

        self.auditor_role.add_to_policy(
            iam.PolicyStatement(
                sid="AuditorLogsRead",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:FilterLogEvents",
                    "logs:DescribeLogGroups",
                ],
                resources=["*"],
            )
        )

        self.auditor_role.add_to_policy(
            iam.PolicyStatement(
                sid="AuditorBedrockInvoke",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[bedrock_auditor_model_arn],
            )
        )

        # ------------------------------------------------------------------ #
        # 2. OmniTrace-Validator-Role                                          #
        #    Permissions: DynamoDB GetItem + Bedrock nova-pro-v1:0             #
        # ------------------------------------------------------------------ #
        self.validator_role = iam.Role(
            self,
            "ValidatorRole",
            role_name=IAM_VALIDATOR_ROLE_NAME,
            assumed_by=lambda_principal,
            managed_policies=[lambda_basic_execution],
            description=(
                "Least-privilege role for OmniTrace Validator Lambda. "
                "Allows DynamoDB GetItem and Bedrock nova-pro-v1:0 invocation."
            ),
        )

        self.validator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ValidatorDynamoDBRead",
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:GetItem"],
                resources=[dynamodb_table_arn],
            )
        )

        self.validator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ValidatorBedrockInvoke",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[bedrock_nova_model_arn],
            )
        )

        # ------------------------------------------------------------------ #
        # 3. OmniTrace-Patcher-Role                                            #
        #    Permissions: DynamoDB write + Bedrock nova-pro + SNS publish      #
        #                 (both topics) + SSM SendCommand (tagged resources)   #
        # ------------------------------------------------------------------ #
        self.patcher_role = iam.Role(
            self,
            "PatcherRole",
            role_name=IAM_PATCHER_ROLE_NAME,
            assumed_by=lambda_principal,
            managed_policies=[lambda_basic_execution],
            description=(
                "Least-privilege role for OmniTrace Patcher Lambda. "
                "Allows DynamoDB writes, Bedrock nova-pro invocation, "
                "SNS publish to both topics, and SSM SendCommand on tagged resources."
            ),
        )

        self.patcher_role.add_to_policy(
            iam.PolicyStatement(
                sid="PatcherDynamoDBWrite",
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                resources=[dynamodb_table_arn],
            )
        )

        self.patcher_role.add_to_policy(
            iam.PolicyStatement(
                sid="PatcherBedrockInvoke",
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[bedrock_nova_model_arn],
            )
        )

        self.patcher_role.add_to_policy(
            iam.PolicyStatement(
                sid="PatcherSNSPublish",
                effect=iam.Effect.ALLOW,
                actions=["sns:Publish"],
                resources=[
                    sns_notifications_arn,
                    sns_sre_escalation_arn,
                ],
            )
        )

        # SSM SendCommand scoped to resources tagged with Project=OmniTrace
        self.patcher_role.add_to_policy(
            iam.PolicyStatement(
                sid="PatcherSSMSendCommand",
                effect=iam.Effect.ALLOW,
                actions=["ssm:SendCommand"],
                resources=["*"],
                conditions={
                    "StringEquals": {
                        "ssm:resourceTag/Project": "OmniTrace",
                    }
                },
            )
        )

        # Allow referencing the AWS-RunShellScript SSM document
        self.patcher_role.add_to_policy(
            iam.PolicyStatement(
                sid="PatcherSSMDocument",
                effect=iam.Effect.ALLOW,
                actions=["ssm:SendCommand"],
                resources=[
                    f"arn:{partition}:ssm:{region}::document/AWS-RunShellScript"
                ],
            )
        )

        # ------------------------------------------------------------------ #
        # 4. OmniTrace-APIHandler-Role                                         #
        #    Permissions: DynamoDB Scan/Get/Update + Step Functions operations  #
        # ------------------------------------------------------------------ #
        self.api_handler_role = iam.Role(
            self,
            "APIHandlerRole",
            role_name=IAM_API_HANDLER_ROLE_NAME,
            assumed_by=lambda_principal,
            managed_policies=[lambda_basic_execution],
            description=(
                "Least-privilege role for OmniTrace API Gateway Lambda handlers. "
                "Allows DynamoDB Scan/GetItem/UpdateItem and Step Functions operations."
            ),
        )

        self.api_handler_role.add_to_policy(
            iam.PolicyStatement(
                sid="APIHandlerDynamoDB",
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:Scan",
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                ],
                resources=[dynamodb_table_arn],
            )
        )

        self.api_handler_role.add_to_policy(
            iam.PolicyStatement(
                sid="APIHandlerStepFunctions",
                effect=iam.Effect.ALLOW,
                actions=[
                    "states:SendTaskSuccess",
                    "states:DescribeExecution",
                ],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------ #
        # 5. OmniTrace-Orchestrator-Role                                       #
        #    Permissions: Lambda InvokeFunction (3 agent ARNs) + DynamoDB      #
        #                 Get/Put/Update + Step Functions SendTaskSuccess       #
        # ------------------------------------------------------------------ #
        self.orchestrator_role = iam.Role(
            self,
            "OrchestratorRole",
            role_name=IAM_ORCHESTRATOR_ROLE_NAME,
            assumed_by=lambda_principal,
            managed_policies=[lambda_basic_execution],
            description=(
                "Least-privilege role for OmniTrace Orchestrator Lambda. "
                "Allows invoking the three agent Lambdas, DynamoDB operations, "
                "and Step Functions SendTaskSuccess."
            ),
        )

        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="OrchestratorLambdaInvoke",
                effect=iam.Effect.ALLOW,
                actions=["lambda:InvokeFunction"],
                resources=[
                    auditor_lambda_arn,
                    validator_lambda_arn,
                    patcher_lambda_arn,
                ],
            )
        )

        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="OrchestratorDynamoDB",
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                resources=[dynamodb_table_arn],
            )
        )

        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="OrchestratorStepFunctions",
                effect=iam.Effect.ALLOW,
                actions=["states:SendTaskSuccess"],
                resources=["*"],
            )
        )
