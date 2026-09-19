"""
OmniTrace Self-Healer Lambda
Executes approved remediation actions from the Validator-approved command set,
updates incident status to RESOLVED, and records the full mitigation log
with timestamps back to DynamoDB.

In production, this would call real AWS service APIs.
For demonstration, it performs mock execution with realistic timing
simulation and records all actions taken.
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
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)
cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)


def _floats_to_decimal(obj: Any) -> Any:
    """Recursively convert float values to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj


def _simulate_command_execution(command_obj: dict, incident_id: str) -> dict[str, Any]:
    """
    Mock-execute a remediation command with realistic simulation.
    In production this would call actual AWS service APIs.
    Records execution timing, output, and result status.
    """
    step = command_obj.get("step", 0)
    command = command_obj.get("command", "")
    description = command_obj.get("description", "")
    est_duration = command_obj.get("estimated_duration_seconds", 5)

    start_time = datetime.now(timezone.utc)

    # Simulate execution duration (capped at 3s for Lambda efficiency)
    simulated_sleep = min(est_duration * 0.1, 3.0)
    time.sleep(simulated_sleep)

    # Determine service type from command to craft realistic mock output
    mock_output = _generate_mock_output(command, incident_id, step)

    end_time = datetime.now(timezone.utc)
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    result = {
        "step": step,
        "description": description,
        "command": command,
        "status": "SUCCESS",
        "executed_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "duration_ms": duration_ms,
        "simulated_estimated_ms": est_duration * 1000,
        "mock_output": mock_output,
        "execution_mode": "SIMULATED",
    }

    logger.info(
        "Command executed (simulated) | step=%d | duration_ms=%d | status=SUCCESS",
        step, duration_ms
    )
    return result


def _generate_mock_output(command: str, incident_id: str, step: int) -> str:
    """Generate realistic mock AWS CLI output based on command type."""
    cmd_lower = command.lower()

    if "ecs update-service" in cmd_lower or "ecs" in cmd_lower:
        return json.dumps({
            "service": {
                "serviceName": command.split("--service")[-1].strip().split()[0] if "--service" in command else "omnitrace-api-service",
                "clusterArn": f"arn:aws:ecs:{AWS_REGION}:123456789012:cluster/omnitrace-cluster",
                "status": "ACTIVE",
                "desiredCount": 3,
                "runningCount": 3,
                "pendingCount": 0,
                "deployments": [
                    {
                        "id": f"ecs-svc/{uuid.uuid4().hex[:16]}",
                        "status": "PRIMARY",
                        "desiredCount": 3,
                        "runningCount": 3,
                        "updatedAt": datetime.now(timezone.utc).isoformat()
                    }
                ]
            }
        }, indent=2)

    elif "autoscaling" in cmd_lower:
        return json.dumps({
            "ResponseMetadata": {
                "RequestId": str(uuid.uuid4()),
                "HTTPStatusCode": 200,
            },
            "message": f"Successfully updated desired capacity for incident {incident_id}"
        }, indent=2)

    elif "lambda update-function" in cmd_lower:
        return json.dumps({
            "FunctionName": "omnitrace-processor",
            "FunctionArn": f"arn:aws:lambda:{AWS_REGION}:123456789012:function:omnitrace-processor",
            "Runtime": "python3.12",
            "LastModified": datetime.now(timezone.utc).isoformat(),
            "State": "Active",
            "LastUpdateStatus": "Successful"
        }, indent=2)

    elif "rds reboot" in cmd_lower:
        return json.dumps({
            "DBInstance": {
                "DBInstanceIdentifier": "omnitrace-db",
                "DBInstanceStatus": "rebooting",
                "DBInstanceClass": "db.r6g.large",
                "Engine": "aurora-postgresql",
                "MultiAZ": True
            }
        }, indent=2)

    elif "elasticache" in cmd_lower:
        return json.dumps({
            "ReplicationGroup": {
                "ReplicationGroupId": "omnitrace-cache",
                "Status": "modifying",
                "Description": "Cache flush initiated for incident remediation"
            }
        }, indent=2)

    else:
        return json.dumps({
            "ResponseMetadata": {"HTTPStatusCode": 200, "RequestId": str(uuid.uuid4())},
            "message": f"Command executed successfully for step {step} | incident: {incident_id}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, indent=2)


def emit_cloudwatch_metric(incident_id: str, downtime_prevented_minutes: int, cost_saved_inr: int) -> None:
    """Emit resolution metrics to CloudWatch for dashboarding."""
    try:
        cloudwatch.put_metric_data(
            Namespace="OmniTrace",
            MetricData=[
                {
                    "MetricName": "IncidentsAutoRemediated",
                    "Value": 1,
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Pipeline", "Value": "OmniTrace"}],
                },
                {
                    "MetricName": "DowntimePreventedMinutes",
                    "Value": float(downtime_prevented_minutes),
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Pipeline", "Value": "OmniTrace"}],
                },
                {
                    "MetricName": "CostSavedINR",
                    "Value": float(cost_saved_inr),
                    "Unit": "Count",
                    "Dimensions": [{"Name": "Pipeline", "Value": "OmniTrace"}],
                },
            ],
        )
        logger.info("CloudWatch metrics emitted | incidentId=%s", incident_id)
    except ClientError as exc:
        logger.warning("CloudWatch metric emit failed (non-fatal): %s", exc)


def write_resolution_record(incident_id: str, timestamp: str, resolution_data: dict) -> None:
    """Write the full resolution record to DynamoDB."""
    now_iso = datetime.now(timezone.utc).isoformat()
    ttl_epoch = int(time.time()) + (90 * 24 * 3600)

    item = {
        "incidentId": incident_id,
        "timestamp": f"RESOLUTION#{timestamp}",
        "agentRole": "SELF_HEALER",
        "status": "RESOLVED",
        "resolvedAt": now_iso,
        "ttl": ttl_epoch,
        "resolutionData": _floats_to_decimal(resolution_data),
    }

    table.put_item(Item=item)
    logger.info("Resolution record written | incidentId=%s", incident_id)


def update_incident_resolved(incident_id: str, timestamp: str, resolution_summary: dict) -> None:
    """Update the primary incident record to RESOLVED with full summary."""
    table.update_item(
        Key={"incidentId": incident_id, "timestamp": timestamp},
        UpdateExpression=(
            "SET #st = :status, resolvedAt = :resolvedAt, "
            "resolutionSummary = :summary, ttl = :ttl"
        ),
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={
            ":status": "AUTO_REMEDIATED",
            ":resolvedAt": datetime.now(timezone.utc).isoformat(),
            ":summary": _floats_to_decimal(resolution_summary),
            ":ttl": int(time.time()) + (90 * 24 * 3600),
        },
    )
    logger.info("Incident marked AUTO_REMEDIATED | incidentId=%s", incident_id)


def handler(event: dict, context: Any) -> dict[str, Any]:
    """
    Main Lambda entry point for the Self-Healer.

    Expects event from Step Functions:
    {
        "incident": {
            "incidentId": "...",
            "timestamp": "...",
            "service": "...",
            ...
        },
        (may contain auditor_result, patcher_result, validator_result at root)
    }
    """
    logger.info("SelfHealer invoked | event_keys=%s", list(event.keys()))

    incident = event.get("incident", event)

    # Flatten nested structure from Step Functions input
    if "incidentId" not in incident and "incidentId" in event:
        incident = event

    incident_id = incident.get("incidentId", str(uuid.uuid4()))
    timestamp = incident.get("timestamp", datetime.now(timezone.utc).isoformat())
    service = incident.get("service", "unknown-service")

    # Extract patcher commands from the pipeline state
    patcher_result = (
        incident.get("patcher_result")
        or event.get("patcher_result")
        or {}
    )
    auditor_result = (
        incident.get("auditor_result")
        or event.get("auditor_result")
        or {}
    )
    validator_result = (
        incident.get("validator_result")
        or event.get("validator_result")
        or {}
    )

    commands = patcher_result.get("commands", [])
    approved_steps = validator_result.get("approved_commands", list(range(1, len(commands) + 1)))

    logger.info(
        "Starting remediation | incidentId=%s | total_commands=%d | approved=%d",
        incident_id, len(commands), len(approved_steps)
    )

    # Filter to only approved commands
    approved_commands = [
        cmd for cmd in commands
        if cmd.get("step") in approved_steps
    ]

    execution_log = []
    total_start = datetime.now(timezone.utc)
    all_success = True

    # Execute each approved remediation command
    for cmd_obj in approved_commands:
        try:
            result = _simulate_command_execution(cmd_obj, incident_id)
            execution_log.append(result)
        except Exception as exc:
            logger.error("Command execution failed | step=%d | error=%s", cmd_obj.get("step"), exc)
            execution_log.append({
                "step": cmd_obj.get("step"),
                "command": cmd_obj.get("command", ""),
                "status": "FAILED",
                "error": str(exc),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            })
            all_success = False

    total_end = datetime.now(timezone.utc)
    total_duration_ms = int((total_end - total_start).total_seconds() * 1000)

    # Calculate impact metrics
    financial_impact = auditor_result.get("financial_impact_inr", {})
    estimated_downtime = auditor_result.get("estimated_downtime_minutes", 15)
    total_cost = financial_impact.get("total", 0)
    downtime_prevented = estimated_downtime if all_success else int(estimated_downtime * 0.5)

    # Build comprehensive resolution summary
    resolution_summary = {
        "healingStrategy": patcher_result.get("remediation_strategy", "Automated remediation"),
        "commandsExecuted": len(execution_log),
        "commandsSucceeded": sum(1 for e in execution_log if e.get("status") == "SUCCESS"),
        "commandsFailed": sum(1 for e in execution_log if e.get("status") == "FAILED"),
        "totalDurationMs": total_duration_ms,
        "allCommandsSucceeded": all_success,
        "executionLog": execution_log,
        "mitigationScript": _build_mitigation_script(approved_commands),
        "impactMetrics": {
            "downtimePreventedMinutes": downtime_prevented,
            "costSavedINR": total_cost,
            "revenueProtectedINR": financial_impact.get("revenue_loss", 0),
            "slaPenaltyAvoidedINR": financial_impact.get("sla_penalty", 0),
            "engineeringHoursSaved": max(1, int(estimated_downtime / 60 * 2)),
        },
        "resolvedAt": total_end.isoformat(),
        "resolvedBy": "OmniTrace-SelfHealer",
        "executionMode": "SIMULATED",
    }

    # Persist resolution record
    write_resolution_record(incident_id, timestamp, resolution_summary)

    # Update primary incident record to RESOLVED
    update_incident_resolved(incident_id, timestamp, resolution_summary)

    # Emit CloudWatch metrics
    emit_cloudwatch_metric(incident_id, downtime_prevented, total_cost)

    final_status = "AUTO_REMEDIATED" if all_success else "PARTIAL_REMEDIATION"
    logger.info(
        "SelfHealer complete | incidentId=%s | status=%s | duration_ms=%d | cost_saved_inr=%d",
        incident_id, final_status, total_duration_ms, total_cost
    )

    return {
        "statusCode": 200,
        "incidentId": incident_id,
        "timestamp": timestamp,
        "status": final_status,
        "service": service,
        "resolution": resolution_summary,
    }


def _build_mitigation_script(commands: list) -> str:
    """Generate a human-readable bash mitigation script from command list."""
    if not commands:
        return "#!/bin/bash\n# No remediation commands were approved\necho 'No actions taken'"

    lines = [
        "#!/bin/bash",
        "# OmniTrace Auto-Generated Remediation Script",
        f"# Generated: {datetime.now(timezone.utc).isoformat()}",
        "# WARNING: Review before running in production",
        "set -e",
        "",
    ]

    for cmd_obj in commands:
        step = cmd_obj.get("step", 0)
        description = cmd_obj.get("description", "")
        command = cmd_obj.get("command", "")
        rollback = cmd_obj.get("rollback_command", "")
        risk = cmd_obj.get("risk_level", "LOW")

        lines.append(f"# Step {step}: {description}")
        lines.append(f"# Risk Level: {risk}")
        lines.append(f"echo 'Executing Step {step}: {description}'")
        lines.append(command)
        lines.append("")

        if rollback:
            lines.append(f"# Rollback for Step {step} (run if step fails):")
            lines.append(f"# {rollback}")
            lines.append("")

    lines.append("echo 'All remediation steps completed successfully'")
    return "\n".join(lines)
