"""
OmniTrace API Handler Lambda
Serves the REST API endpoints consumed by the React SPA:
  GET  /api/incidents           — list all incidents (paginated, sorted newest first)
  GET  /api/incidents/{id}      — get single incident with full agent reasoning trail
  POST /api/trigger             — create a simulated incident and fire EventBridge event
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
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE"]
EVENTBRIDGE_BUS = os.environ.get("EVENTBRIDGE_BUS", "default")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
events_client = boto3.client("events", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


# ─────────────────────────────────────────────────────────────────────────────
# Serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj) if obj % 1 else int(obj)
        return super().default(obj)


def _serialize(obj: Any) -> str:
    return json.dumps(obj, cls=DecimalEncoder)


def _response(status_code: int, body: Any, headers: dict | None = None) -> dict:
    """Build a Lambda-proxy HTTP response."""
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Cache-Control": "no-cache",
    }
    if headers:
        default_headers.update(headers)

    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": _serialize(body) if not isinstance(body, str) else body,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Simulated incident scenarios
# ─────────────────────────────────────────────────────────────────────────────

INCIDENT_SCENARIOS = [
    {
        "service": "omnitrace-api-gateway",
        "errorType": "MEMORY_EXHAUSTION",
        "severity": "P1",
        "description": "API Gateway Lambda hitting 512MB memory limit",
        "errorLogs": """[ERROR] 2025-01-15T14:32:11Z - INIT_REPORT Init Duration: 4521.23 ms
[ERROR] 2025-01-15T14:32:15Z - REPORT RequestId: a7f3b291 Duration: 29834.12 ms Billed Duration: 29835 ms Memory Size: 512 MB Max Memory Used: 511 MB
[ERROR] 2025-01-15T14:32:15Z - Runtime.ExitError: RequestId: a7f3b291 Error: Runtime exited with error: signal: killed
[ERROR] 2025-01-15T14:32:16Z - java.lang.OutOfMemoryError: Java heap space
[ERROR] 2025-01-15T14:32:16Z - com.amazonaws.services.lambda.runtime.LambdaRuntime: Lambda function failed to initialize
[CRITICAL] 2025-01-15T14:32:18Z - 847 requests failed in last 60 seconds - Error rate 73.2%
[CRITICAL] 2025-01-15T14:32:20Z - CloudWatch Alarm: APIGateway5XXError ALARM - 847 errors in 1 min
[ERROR] 2025-01-15T14:32:21Z - DynamoDB ProvisionedThroughputExceededException: Table OmniTrace_Incidents
[ERROR] 2025-01-15T14:32:22Z - Connection pool exhausted: 500/500 connections used
[CRITICAL] 2025-01-15T14:32:23Z - Health check FAILED - /health returning 503 Service Unavailable""",
    },
    {
        "service": "omnitrace-data-pipeline",
        "errorType": "DATABASE_CONNECTION_POOL_EXHAUSTION",
        "severity": "P1",
        "description": "RDS Aurora connection pool exhausted causing cascade failures",
        "errorLogs": """[ERROR] 2025-01-15T09:15:33Z - FATAL: remaining connection slots are reserved for non-replication superuser connections
[ERROR] 2025-01-15T09:15:34Z - pg_stat_activity shows 498/500 max connections active
[ERROR] 2025-01-15T09:15:35Z - HikariPool-1 - Connection is not available, request timed out after 30000ms
[ERROR] 2025-01-15T09:15:36Z - TaskExecutor-12: Cannot execute query: connection pool exhausted
[CRITICAL] 2025-01-15T09:15:37Z - Data pipeline STALLED - 0 records processed in last 5 minutes
[ERROR] 2025-01-15T09:15:38Z - Celery worker omnitrace-worker-7 LOST: heartbeat timeout
[ERROR] 2025-01-15T09:15:39Z - Redis connection timeout: ECONNTIMEOUT 10.0.1.45:6379
[CRITICAL] 2025-01-15T09:15:40Z - ECS service omnitrace-pipeline running 1/6 desired tasks
[ERROR] 2025-01-15T09:15:41Z - SNS publish failed: NetworkingError: connect ETIMEDOUT
[CRITICAL] 2025-01-15T09:15:42Z - SLA breach imminent: 847 orders pending processing > 15min threshold""",
    },
    {
        "service": "omnitrace-auth-service",
        "errorType": "JWT_VALIDATION_TIMEOUT",
        "severity": "P2",
        "description": "JWT validation Lambda timing out causing auth failures across all services",
        "errorLogs": """[ERROR] 2025-01-15T11:42:07Z - Task timed out after 30.00 seconds: arn:aws:lambda:us-east-1:123456789012:function:omnitrace-jwt-validator
[ERROR] 2025-01-15T11:42:08Z - HTTPSConnectionPool(host='cognito-idp.us-east-1.amazonaws.com', port=443): Read timed out. (read timeout=5)
[ERROR] 2025-01-15T11:42:09Z - jwt.exceptions.DecodeError: It is required that you pass in a value for the "algorithms" argument
[ERROR] 2025-01-15T11:42:10Z - 401 Unauthorized: Token validation failed for user_id=usr_8f2k3m
[CRITICAL] 2025-01-15T11:42:11Z - Auth failure rate: 94.7% - CRITICAL threshold exceeded
[ERROR] 2025-01-15T11:42:12Z - Cognito User Pool throttled: TooManyRequestsException
[ERROR] 2025-01-15T11:42:13Z - Cache miss rate: 99.8% - Redis cluster unreachable
[ERROR] 2025-01-15T11:42:14Z - 2847 user sessions invalidated due to token re-validation cascade
[CRITICAL] 2025-01-15T11:42:15Z - Customer impact: 2847 active sessions disrupted
[ERROR] 2025-01-15T11:42:16Z - Dead letter queue depth: 8,432 unprocessed auth events""",
    },
    {
        "service": "omnitrace-ml-inference",
        "errorType": "GPU_MEMORY_OVERFLOW",
        "severity": "P2",
        "description": "ML inference service OOM on SageMaker endpoint",
        "errorLogs": """[ERROR] 2025-01-15T16:05:22Z - CUDA out of memory. Tried to allocate 4.50 GiB
[ERROR] 2025-01-15T16:05:23Z - RuntimeError: CUDA error: out of memory (device 0)
[ERROR] 2025-01-15T16:05:24Z - Prediction service: ModelLoadException - Unable to load model weights
[ERROR] 2025-01-15T16:05:25Z - SageMaker endpoint omnitrace-inference-prod InService → OutOfService
[CRITICAL] 2025-01-15T16:05:26Z - ML predictions unavailable - 0/3 instances healthy
[ERROR] 2025-01-15T16:05:27Z - Fallback to rule-based engine failed: RuleEngineException
[ERROR] 2025-01-15T16:05:28Z - torch.cuda.OutOfMemoryError: CUDA out of memory
[CRITICAL] 2025-01-15T16:05:29Z - Batch inference job failed: 47,832 predictions pending
[ERROR] 2025-01-15T16:05:30Z - Model checkpoint corrupt: md5 mismatch on epoch_142.pt
[CRITICAL] 2025-01-15T16:05:31Z - Revenue impact: Recommendation engine offline - CTR dropping""",
    },
    {
        "service": "omnitrace-event-processor",
        "errorType": "KINESIS_SHARD_ITERATOR_EXPIRED",
        "severity": "P2",
        "description": "Kinesis consumer shard iterators expired causing event processing lag",
        "errorLogs": """[ERROR] 2025-01-15T13:21:44Z - ExpiredIteratorException: The shard iterator has expired
[ERROR] 2025-01-15T13:21:45Z - Kinesis stream omnitrace-events: GetRecords failed after 3 retries
[ERROR] 2025-01-15T13:21:46Z - Consumer lag: 8,423,771 records behind in shard shardId-000000000003
[CRITICAL] 2025-01-15T13:21:47Z - Event processing delay: 47 minutes behind real-time
[ERROR] 2025-01-15T13:21:48Z - Lambda ESM: Batch failure - 500 records in DLQ
[ERROR] 2025-01-15T13:21:49Z - DynamoDB ConditionalCheckFailedException: optimistic lock violation
[CRITICAL] 2025-01-15T13:21:50Z - Order processing pipeline: 12,847 orders stuck in PROCESSING state
[ERROR] 2025-01-15T13:21:51Z - SQS queue omnitrace-order-dlq depth: 8,432 messages
[ERROR] 2025-01-15T13:21:52Z - CloudWatch Metric: IteratorAge P99=2847000ms (threshold: 60000ms)
[CRITICAL] 2025-01-15T13:21:53Z - SLA breach: 3847 orders past 30-minute processing SLA""",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Route handlers
# ─────────────────────────────────────────────────────────────────────────────

def handle_get_incidents(query_params: dict) -> dict:
    """
    GET /api/incidents
    Returns paginated list of incidents sorted by timestamp descending.
    """
    limit = min(int(query_params.get("limit", 20)), 100)

    try:
        response = table.scan(
            Limit=200,
        )
        items = response.get("Items", [])

        # Filter to only primary incident records (no AUDITOR#, PATCHER# etc. sub-records)
        incidents = [
            item for item in items
            if not item.get("timestamp", "").startswith(("AUDITOR#", "PATCHER#", "VALIDATOR#", "RESOLUTION#"))
        ]

        # Sort by timestamp descending (newest first)
        incidents.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        incidents = incidents[:limit]

        # Sanitize for JSON serialization
        return _response(200, {
            "incidents": incidents,
            "count": len(incidents),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    except ClientError as exc:
        logger.error("DynamoDB scan failed: %s", exc)
        return _response(500, {"error": "Failed to retrieve incidents", "detail": str(exc)})


def handle_get_incident_by_id(incident_id: str) -> dict:
    """
    GET /api/incidents/{incidentId}
    Returns single incident with full agent reasoning trail.
    """
    try:
        response = table.query(
            KeyConditionExpression=Key("incidentId").eq(incident_id),
            ScanIndexForward=True,
        )
        items = response.get("Items", [])

        if not items:
            return _response(404, {"error": f"Incident {incident_id} not found"})

        # Separate primary record from agent sub-records
        primary = next(
            (i for i in items if not i.get("timestamp", "").startswith(("AUDITOR#", "PATCHER#", "VALIDATOR#", "RESOLUTION#"))),
            items[0]
        )
        agent_states = [i for i in items if i != primary]

        return _response(200, {
            "incident": primary,
            "agentTrail": agent_states,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    except ClientError as exc:
        logger.error("DynamoDB query failed | incidentId=%s | error=%s", incident_id, exc)
        return _response(500, {"error": "Failed to retrieve incident", "detail": str(exc)})


def handle_trigger_simulation(body: dict) -> dict:
    """
    POST /api/trigger
    Creates a simulated cloud incident and fires an EventBridge event
    to kick off the OmniTrace triage pipeline.
    """
    import random

    scenario_index = body.get("scenarioIndex")
    if scenario_index is not None and 0 <= int(scenario_index) < len(INCIDENT_SCENARIOS):
        scenario = INCIDENT_SCENARIOS[int(scenario_index)]
    else:
        scenario = random.choice(INCIDENT_SCENARIOS)

    incident_id = f"INC-{int(time.time())}-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()
    ttl_epoch = int(time.time()) + (90 * 24 * 3600)

    # Write initial incident record to DynamoDB
    incident_record = {
        "incidentId": incident_id,
        "timestamp": timestamp,
        "service": scenario["service"],
        "errorType": scenario["errorType"],
        "severity": scenario["severity"],
        "description": scenario["description"],
        "errorLogs": scenario["errorLogs"],
        "region": AWS_REGION,
        "status": "TRIGGERED",
        "triggeredAt": timestamp,
        "triggeredBy": body.get("triggeredBy", "UI_SIMULATION"),
        "ttl": ttl_epoch,
        "source": "omnitrace.alert",
    }

    try:
        table.put_item(Item=incident_record)
        logger.info("Incident record created | incidentId=%s | service=%s", incident_id, scenario["service"])
    except ClientError as exc:
        logger.error("Failed to create incident record: %s", exc)
        return _response(500, {"error": "Failed to create incident record", "detail": str(exc)})

    # Fire EventBridge event to start the triage pipeline
    event_detail = {
        "incidentId": incident_id,
        "service": scenario["service"],
        "errorType": scenario["errorType"],
        "severity": scenario["severity"],
        "region": AWS_REGION,
        "errorLogs": scenario["errorLogs"],
        "timestamp": timestamp,
        "description": scenario["description"],
    }

    try:
        eb_response = events_client.put_events(
            Entries=[
                {
                    "Source": "omnitrace.alert",
                    "DetailType": "OmniTraceIncident",
                    "Detail": json.dumps(event_detail),
                    "EventBusName": EVENTBRIDGE_BUS,
                    "Time": datetime.now(timezone.utc),
                }
            ]
        )

        failed_count = eb_response.get("FailedEntryCount", 0)
        if failed_count > 0:
            logger.error("EventBridge put_events partial failure: %s", eb_response)
            return _response(500, {
                "error": "EventBridge event delivery failed",
                "detail": eb_response.get("Entries", []),
            })

        eb_event_id = eb_response["Entries"][0].get("EventId", "unknown")
        logger.info(
            "EventBridge event fired | incidentId=%s | eventId=%s",
            incident_id, eb_event_id
        )

    except ClientError as exc:
        logger.error("EventBridge put_events failed: %s", exc)
        return _response(500, {"error": "Failed to trigger pipeline", "detail": str(exc)})

    return _response(201, {
        "message": "Incident simulation triggered successfully",
        "incidentId": incident_id,
        "timestamp": timestamp,
        "service": scenario["service"],
        "errorType": scenario["errorType"],
        "severity": scenario["severity"],
        "eventBridgeEventId": eb_event_id,
        "status": "TRIGGERED",
        "pipelineStatus": "STARTING",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Lambda Handler
# ─────────────────────────────────────────────────────────────────────────────

def handler(event: dict, context: Any) -> dict:
    """
    Main Lambda handler for the REST API.
    Routes requests based on HTTP method and path.
    """
    method = event.get("requestContext", {}).get("http", {}).get("method", "").upper()
    raw_path = event.get("rawPath", event.get("path", ""))
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    body_str = event.get("body", "{}")

    logger.info("API request | method=%s | path=%s", method, raw_path)

    # Parse body
    try:
        body = json.loads(body_str) if body_str else {}
    except json.JSONDecodeError:
        body = {}

    # OPTIONS preflight
    if method == "OPTIONS":
        return _response(200, {"message": "OK"})

    # Route: GET /api/incidents/{incidentId}
    if method == "GET" and path_params.get("incidentId"):
        return handle_get_incident_by_id(path_params["incidentId"])

    # Route: GET /api/incidents
    if method == "GET" and ("/api/incidents" in raw_path or "/incidents" in raw_path):
        return handle_get_incidents(query_params)

    # Route: POST /api/trigger
    if method == "POST" and ("/api/trigger" in raw_path or "/trigger" in raw_path):
        return handle_trigger_simulation(body)

    return _response(404, {
        "error": "Route not found",
        "method": method,
        "path": raw_path,
        "availableRoutes": [
            "GET /api/incidents",
            "GET /api/incidents/{incidentId}",
            "POST /api/trigger",
        ],
    })
