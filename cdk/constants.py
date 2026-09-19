"""
Shared constants for the OmniTrace CDK stack.

All CDK constructs should import from this module to ensure consistency
across the stack definition.
"""

# Stack identity
STACK_NAME = "OmniTraceStack"
APP_NAME = "OmniTrace"

# AWS deployment target — override via CDK context or environment variables if needed
AWS_REGION = "us-east-1"
AWS_ACCOUNT = ""  # Leave empty to use the CDK default (current CLI account)

# DynamoDB
DYNAMODB_TABLE_NAME = "OmniTraceIncidents"
DYNAMODB_PK_NAME = "IncidentID"
DYNAMODB_SK_NAME = "Timestamp"
DYNAMODB_TTL_ATTRIBUTE = "ExpiresAt"
INCIDENT_TTL_DAYS = 90

# SNS topic names
SNS_NOTIFICATIONS_TOPIC_NAME = "OmniTrace-Notifications"
SNS_SRE_ESCALATION_TOPIC_NAME = "OmniTrace-SRE-Escalation"

# SQS dead-letter queue
SQS_DLQ_NAME = "OmniTrace-EventBridge-DLQ"

# EventBridge
EVENTBRIDGE_SOURCE = "omnitrace.simulator"
EVENTBRIDGE_DETAIL_TYPE = "OmniTraceIncident"
EVENTBRIDGE_RULE_NAME = "OmniTrace-IncidentRule"

# IAM role names
IAM_AUDITOR_ROLE_NAME = "OmniTrace-Auditor-Role"
IAM_VALIDATOR_ROLE_NAME = "OmniTrace-Validator-Role"
IAM_PATCHER_ROLE_NAME = "OmniTrace-Patcher-Role"
IAM_ORCHESTRATOR_ROLE_NAME = "OmniTrace-Orchestrator-Role"
IAM_API_HANDLER_ROLE_NAME = "OmniTrace-APIHandler-Role"

# Lambda function names
LAMBDA_AUDITOR_NAME = "OmniTrace-Auditor"
LAMBDA_VALIDATOR_NAME = "OmniTrace-Validator"
LAMBDA_PATCHER_NAME = "OmniTrace-Patcher"
LAMBDA_SIMULATOR_NAME = "OmniTrace-Simulator"
LAMBDA_CREATE_RECORD_NAME = "OmniTrace-CreateRecord"
LAMBDA_UPDATE_STATUS_NAME = "OmniTrace-UpdateStatus"

# Lambda timeouts (seconds)
LAMBDA_AUDITOR_TIMEOUT_S = 60
LAMBDA_VALIDATOR_TIMEOUT_S = 45
LAMBDA_PATCHER_TIMEOUT_S = 90
LAMBDA_DEFAULT_TIMEOUT_S = 30

# Lambda runtime
LAMBDA_PYTHON_RUNTIME = "python3.12"

# Step Functions
SFN_STATE_MACHINE_NAME = "OmniTrace-Orchestrator"
SFN_EXECUTION_HISTORY_RETENTION_DAYS = 90

# API Gateway
APIGW_NAME = "OmniTrace-API"

# Bedrock model IDs
BEDROCK_AUDITOR_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"
BEDROCK_VALIDATOR_MODEL_ID = "amazon.nova-pro-v1:0"
BEDROCK_PATCHER_MODEL_ID = "amazon.nova-pro-v1:0"

# CloudWatch
CW_NAMESPACE = "OmniTrace"
CW_METRIC_RESOLUTION_TIME = "IncidentResolutionTimeMs"
CW_METRIC_COST_SAVED = "RemediationCostSavedINR"
CW_RESOLUTION_ALARM_THRESHOLD_MS = 30_000
CW_LOG_RETENTION_DAYS = 90

# Amplify
AMPLIFY_APP_NAME = "OmniTrace-Dashboard"
AMPLIFY_BRANCH_NAME = "main"

# Tags applied to all stack resources
RESOURCE_TAGS = {
    "Project": APP_NAME,
    "ManagedBy": "CDK",
}
