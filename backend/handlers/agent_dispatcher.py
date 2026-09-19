"""
OmniTrace Agent Dispatcher
Lambda function implementing AUDITOR, PATCHER, and VALIDATOR agents
using the Amazon Bedrock Converse API with amazon.nova-pro-v1:0.

Each agent role produces structured JSON output and persists
its reasoning chain directly to DynamoDB for full auditability.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-pro-v1:0")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


# ─────────────────────────────────────────────────────────────────────────────
# Agent System Prompts
# ─────────────────────────────────────────────────────────────────────────────

AUDITOR_SYSTEM_PROMPT = """You are the AUDITOR agent in OmniTrace, an autonomous cloud incident triage system.

Your mission: Perform deep root-cause analysis on cloud incidents and estimate financial impact in Indian Rupees (INR).

ANALYSIS FRAMEWORK:
1. Parse the raw CloudWatch error logs to identify the exact failure point
2. Determine the error category: memory leak, timeout, dependency failure, config error, capacity breach, network partition
3. Calculate blast radius: which services are affected downstream
4. Estimate downtime duration based on error patterns
5. Calculate financial impact in INR:
   - Average SaaS revenue loss: ₹8,500 per minute of downtime
   - Data processing delays: ₹1,200 per minute per affected pipeline
   - SLA breach penalties: ₹50,000 per hour for P1 incidents
   - Engineering hours cost: ₹3,500 per engineer-hour for incident response

OUTPUT FORMAT - respond with valid JSON only:
{
  "root_cause": "specific technical root cause in one sentence",
  "error_category": "one of: MEMORY_LEAK | TIMEOUT | DEPENDENCY_FAILURE | CONFIG_ERROR | CAPACITY_BREACH | NETWORK_PARTITION | DATABASE_ERROR | AUTH_FAILURE",
  "affected_services": ["list", "of", "impacted", "services"],
  "blast_radius": "CONTAINED | MODERATE | WIDESPREAD | CRITICAL",
  "estimated_downtime_minutes": <integer>,
  "financial_impact_inr": {
    "revenue_loss": <integer>,
    "sla_penalty": <integer>,
    "engineering_cost": <integer>,
    "total": <integer>
  },
  "confidence_score": <float 0.0-1.0>,
  "reasoning_chain": ["step1", "step2", "step3"],
  "recommended_severity": "P1 | P2 | P3"
}"""


PATCHER_SYSTEM_PROMPT = """You are the PATCHER agent in OmniTrace, an autonomous cloud self-healing system.

Your mission: Generate precise, non-destructive AWS CLI / infrastructure remediation commands based on the AUDITOR's diagnosis.

SAFETY RULES - STRICTLY ENFORCED:
- NEVER generate commands that delete databases, tables, or S3 buckets
- NEVER touch IAM credentials, access keys, or security groups with 0.0.0.0/0
- NEVER scale DOWN below minimum healthy capacity
- NEVER stop ALL instances of a service simultaneously (rolling restart only)
- ALWAYS include a rollback command for every remediation command
- ALWAYS prefer non-destructive operations: restart > replace, scale > delete
- MAXIMUM 5 remediation commands per incident

COMMAND TYPES ALLOWED:
- aws ecs update-service (for ECS service restart/scaling)
- aws lambda update-function-configuration (for Lambda config changes)
- aws autoscaling set-desired-capacity (for ASG scaling)
- aws elasticache modify-replication-group (for cache flush)
- aws rds reboot-db-instance (for non-destructive DB restart only)
- aws cloudwatch put-metric-alarm (for alert threshold adjustment)
- aws application-autoscaling register-scalable-target (for scaling policy)

OUTPUT FORMAT - respond with valid JSON only:
{
  "remediation_strategy": "one-sentence description of the overall fix approach",
  "commands": [
    {
      "step": 1,
      "description": "human-readable description",
      "command": "exact aws cli command with all flags",
      "rollback_command": "exact rollback aws cli command",
      "estimated_duration_seconds": <integer>,
      "risk_level": "LOW | MEDIUM"
    }
  ],
  "total_remediation_time_seconds": <integer>,
  "expected_outcome": "what will be fixed after executing these commands",
  "reasoning_chain": ["why step1", "why step2"]
}"""


VALIDATOR_SYSTEM_PROMPT = """You are the VALIDATOR agent in OmniTrace, the safety guardian of the autonomous remediation pipeline.

Your mission: Perform a comprehensive security and safety audit of the PATCHER's remediation commands. 
You have FINAL AUTHORITY to VETO any unsafe remediation.

AUTOMATIC VETO TRIGGERS - immediately emit VETO if ANY command:
1. Contains: DROP, DELETE, TRUNCATE, DESTROY, TERMINATE, REMOVE related to databases or storage
2. Modifies IAM roles, policies, access keys, or security credentials
3. Removes security group rules or opens ports to 0.0.0.0/0 or ::/0
4. Scales a service to 0 instances (complete shutdown)
5. Deletes S3 buckets, objects, or CloudFront distributions without explicit backup confirmation
6. Modifies production KMS keys or encryption settings
7. Touches Route53 records for production domains without DNS TTL verification
8. Bypasses MFA or disables CloudTrail logging

EXECUTE APPROVAL CRITERIA - approve only if ALL are true:
- Commands are strictly limited to restart, scale-up, configuration adjustment
- Every command has a corresponding rollback command
- Risk levels are all LOW or MEDIUM (no HIGH risk commands)
- No data destruction or irreversible operations
- Commands target specific resource ARNs (not wildcards)

OUTPUT FORMAT - respond with valid JSON only:
{
  "verdict": "EXECUTE | VETO",
  "veto_reason": "null if EXECUTE, specific reason if VETO",
  "safety_checks": [
    {
      "check": "check name",
      "result": "PASS | FAIL",
      "detail": "specific finding"
    }
  ],
  "risk_assessment": "LOW | MEDIUM | HIGH | CRITICAL",
  "approved_commands": [<list of step numbers approved, empty array if VETO>],
  "modifications_required": ["list any required modifications before execution"],
  "reasoning_chain": ["security check 1", "security check 2"]
}"""


# ─────────────────────────────────────────────────────────────────────────────
# Bedrock Converse API wrapper
# ─────────────────────────────────────────────────────────────────────────────

def invoke_bedrock_agent(system_prompt: str, user_message: str, incident_id: str, agent_role: str) -> dict[str, Any]:
    """
    Call the Bedrock Converse API and return the parsed JSON response.
    Implements exponential backoff for throttling.
    """
    messages = [
        {
            "role": "user",
            "content": [{"text": user_message}]
        }
    ]

    inference_config = {
        "maxTokens": 4096,
        "temperature": 0.1,
        "topP": 0.9,
    }

    max_retries = 4
    base_delay = 2

    for attempt in range(max_retries):
        try:
            logger.info(
                "Invoking Bedrock %s | model=%s | incident=%s | attempt=%d",
                agent_role, BEDROCK_MODEL_ID, incident_id, attempt + 1
            )

            response = bedrock.converse(
                modelId=BEDROCK_MODEL_ID,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig=inference_config,
            )

            raw_text = response["output"]["message"]["content"][0]["text"]
            usage = response.get("usage", {})

            logger.info(
                "Bedrock response received | agent=%s | inputTokens=%d | outputTokens=%d",
                agent_role,
                usage.get("inputTokens", 0),
                usage.get("outputTokens", 0)
            )

            # Strip markdown code fences if model wraps JSON
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            parsed = json.loads(cleaned)
            parsed["_model_id"] = BEDROCK_MODEL_ID
            parsed["_input_tokens"] = usage.get("inputTokens", 0)
            parsed["_output_tokens"] = usage.get("outputTokens", 0)
            return parsed

        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"):
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning("Bedrock throttled, retrying in %ds | attempt=%d", delay, attempt + 1)
                    time.sleep(delay)
                    continue
            logger.error("Bedrock ClientError: %s | code=%s", exc, error_code)
            raise

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Bedrock JSON response: %s | raw=%s", exc, raw_text[:500])
            # Return a structured fallback so pipeline can continue
            return {
                "error": f"JSON parse failure: {str(exc)}",
                "raw_response": raw_text[:2000],
                "_model_id": BEDROCK_MODEL_ID,
            }

    raise RuntimeError(f"Bedrock {agent_role} exceeded max retries for incident {incident_id}")


# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _floats_to_decimal(obj: Any) -> Any:
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj


def write_agent_state(incident_id: str, timestamp: str, agent_role: str, status: str, payload: dict) -> None:
    """Persist agent state and reasoning to DynamoDB."""
    now_iso = datetime.now(timezone.utc).isoformat()
    ttl_epoch = int(time.time()) + (90 * 24 * 3600)  # 90 days

    item = {
        "incidentId": incident_id,
        "timestamp": timestamp,
        "agentRole": agent_role,
        "status": status,
        "updatedAt": now_iso,
        "ttl": ttl_epoch,
        "agentPayload": _floats_to_decimal(payload),
    }

    try:
        table.put_item(Item=item)
        logger.info("DynamoDB write success | incidentId=%s | agent=%s | status=%s", incident_id, agent_role, status)
    except ClientError as exc:
        logger.error("DynamoDB write failed | error=%s", exc)
        raise


def update_incident_status(incident_id: str, timestamp: str, status: str, extra_attrs: dict | None = None) -> None:
    """Update the incident status field and optional additional attributes."""
    update_expr = "SET #st = :status, updatedAt = :ts"
    expr_names = {"#st": "status"}
    expr_values = {
        ":status": status,
        ":ts": datetime.now(timezone.utc).isoformat(),
    }

    if extra_attrs:
        for key, val in extra_attrs.items():
            safe_key = f"#{key}"
            update_expr += f", {safe_key} = :{key}"
            expr_names[safe_key] = key
            expr_values[f":{key}"] = _floats_to_decimal(val)

    try:
        table.update_item(
            Key={"incidentId": incident_id, "timestamp": timestamp},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
    except ClientError as exc:
        logger.error("DynamoDB update failed | incidentId=%s | error=%s", incident_id, exc)
        raise


def get_incident(incident_id: str, timestamp: str) -> dict | None:
    """Fetch a single incident from DynamoDB."""
    try:
        resp = table.get_item(Key={"incidentId": incident_id, "timestamp": timestamp})
        return resp.get("Item")
    except ClientError as exc:
        logger.error("DynamoDB get failed | incidentId=%s | error=%s", incident_id, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Agent Role Handlers
# ─────────────────────────────────────────────────────────────────────────────

def run_auditor(incident: dict) -> dict[str, Any]:
    """
    AUDITOR agent: root-cause analysis and financial impact estimation.
    Updates DynamoDB status to AUDITOR_DIAGNOSING then AUDITOR_COMPLETE.
    """
    incident_id = incident["incidentId"]
    timestamp = incident.get("timestamp", datetime.now(timezone.utc).isoformat())

    update_incident_status(incident_id, timestamp, "AUDITOR_DIAGNOSING")

    error_logs = incident.get("errorLogs", "No logs provided")
    service = incident.get("service", "unknown-service")
    severity = incident.get("severity", "P2")
    region = incident.get("region", "us-east-1")
    error_type = incident.get("errorType", "Unknown")

    user_message = f"""INCIDENT REPORT FOR IMMEDIATE TRIAGE:

Incident ID: {incident_id}
Service: {service}
Error Type: {error_type}
Severity: {severity}
Region: {region}
Timestamp: {timestamp}

RAW CLOUDWATCH ERROR LOGS:
{error_logs}

Perform full root-cause analysis and calculate financial impact in INR. Respond with JSON only."""

    result = invoke_bedrock_agent(
        system_prompt=AUDITOR_SYSTEM_PROMPT,
        user_message=user_message,
        incident_id=incident_id,
        agent_role="AUDITOR",
    )

    write_agent_state(
        incident_id=incident_id,
        timestamp=f"AUDITOR#{timestamp}",
        agent_role="AUDITOR",
        status="COMPLETE",
        payload=result,
    )

    update_incident_status(
        incident_id, timestamp, "PATCHER_DRAFTING",
        extra_attrs={"auditorResult": result}
    )

    logger.info("AUDITOR complete | incidentId=%s | root_cause=%s", incident_id, result.get("root_cause", "N/A"))
    return result


def run_patcher(incident: dict) -> dict[str, Any]:
    """
    PATCHER agent: generates non-destructive remediation commands.
    Updates DynamoDB status to PATCHER_DRAFTING then PATCHER_COMPLETE.
    """
    incident_id = incident["incidentId"]
    timestamp = incident.get("timestamp", datetime.now(timezone.utc).isoformat())

    auditor_result = incident.get("auditor_result", {})
    service = incident.get("service", "unknown-service")
    region = incident.get("region", "us-east-1")
    error_type = incident.get("errorType", "Unknown")

    user_message = f"""GENERATE REMEDIATION COMMANDS

Service: {service}
Region: {region}
Error Type: {error_type}
Incident ID: {incident_id}

AUDITOR DIAGNOSIS:
{json.dumps(auditor_result, indent=2)}

Generate precise, non-destructive AWS CLI remediation commands. Respond with JSON only."""

    result = invoke_bedrock_agent(
        system_prompt=PATCHER_SYSTEM_PROMPT,
        user_message=user_message,
        incident_id=incident_id,
        agent_role="PATCHER",
    )

    write_agent_state(
        incident_id=incident_id,
        timestamp=f"PATCHER#{timestamp}",
        agent_role="PATCHER",
        status="COMPLETE",
        payload=result,
    )

    update_incident_status(
        incident_id, timestamp, "VALIDATOR_CHECKING",
        extra_attrs={"patcherResult": result}
    )

    logger.info("PATCHER complete | incidentId=%s | strategy=%s", incident_id, result.get("remediation_strategy", "N/A"))
    return result


def run_validator(incident: dict) -> dict[str, Any]:
    """
    VALIDATOR agent: safety audit on patcher commands, emits VETO or EXECUTE.
    Updates DynamoDB status to VALIDATOR_CHECKING then stores verdict.
    """
    incident_id = incident["incidentId"]
    timestamp = incident.get("timestamp", datetime.now(timezone.utc).isoformat())

    patcher_result = incident.get("patcher_result", {})
    auditor_result = incident.get("auditor_result", {})
    service = incident.get("service", "unknown-service")

    user_message = f"""SAFETY AUDIT REQUEST

Service: {service}
Incident ID: {incident_id}

AUDITOR ROOT CAUSE:
{json.dumps(auditor_result, indent=2)}

PATCHER REMEDIATION PLAN:
{json.dumps(patcher_result, indent=2)}

Perform comprehensive safety audit. Issue EXECUTE or VETO verdict. Respond with JSON only."""

    result = invoke_bedrock_agent(
        system_prompt=VALIDATOR_SYSTEM_PROMPT,
        user_message=user_message,
        incident_id=incident_id,
        agent_role="VALIDATOR",
    )

    verdict = result.get("verdict", "VETO")
    next_status = "AUTO_REMEDIATING" if verdict == "EXECUTE" else "ESCALATED_TO_SRE"

    write_agent_state(
        incident_id=incident_id,
        timestamp=f"VALIDATOR#{timestamp}",
        agent_role="VALIDATOR",
        status="COMPLETE",
        payload=result,
    )

    update_incident_status(
        incident_id, timestamp, next_status,
        extra_attrs={"validatorResult": result, "verdict": verdict}
    )

    logger.info("VALIDATOR complete | incidentId=%s | verdict=%s", incident_id, verdict)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Lambda Handler
# ─────────────────────────────────────────────────────────────────────────────

def handler(event: dict, context: Any) -> dict[str, Any]:
    """
    Main Lambda entry point for the Agent Dispatcher.

    Expects event shape:
    {
        "agent_role": "AUDITOR" | "PATCHER" | "VALIDATOR",
        "incident": { ...incident payload from EventBridge/Step Functions... }
    }
    """
    logger.info("AgentDispatcher invoked | event=%s", json.dumps(event, default=str))

    agent_role = event.get("agent_role", "").upper()
    incident = event.get("incident", event)

    # If invoked directly from Step Functions, the incident data may be at root level
    if "incidentId" not in incident and "incidentId" in event:
        incident = event

    incident_id = incident.get("incidentId")
    if not incident_id:
        incident_id = str(uuid.uuid4())
        incident["incidentId"] = incident_id
        logger.warning("No incidentId in event, generated: %s", incident_id)

    timestamp = incident.get("timestamp", datetime.now(timezone.utc).isoformat())
    incident["timestamp"] = timestamp

    try:
        if agent_role == "AUDITOR":
            result = run_auditor(incident)
        elif agent_role == "PATCHER":
            result = run_patcher(incident)
        elif agent_role == "VALIDATOR":
            result = run_validator(incident)
        else:
            raise ValueError(f"Unknown agent_role: '{agent_role}'. Must be AUDITOR, PATCHER, or VALIDATOR.")

        return {
            "statusCode": 200,
            "incidentId": incident_id,
            "timestamp": timestamp,
            "agent_role": agent_role,
            "verdict": result.get("verdict"),
            **result,
        }

    except Exception as exc:
        logger.exception("AgentDispatcher fatal error | agent=%s | incident=%s | error=%s", agent_role, incident_id, exc)

        # Attempt to mark the incident as FAILED in DynamoDB
        try:
            update_incident_status(incident_id, timestamp, "PIPELINE_ERROR",
                                   extra_attrs={"errorMessage": str(exc)})
        except Exception:
            pass

        raise
