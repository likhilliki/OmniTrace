# Design Document — OmniTrace

## Overview

OmniTrace is an autonomous incident detection and remediation platform. It ingests operational anomaly events via Amazon EventBridge, drives them through a three-agent AI pipeline (Auditor → Validator → Patcher) coordinated by AWS Step Functions, persists incident state in DynamoDB, exposes REST APIs via API Gateway, and renders telemetry on a React/Tailwind/Vite dashboard hosted on AWS Amplify. All cost-savings metrics are denominated in INR.

---

## Architecture

### System Context Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                   OmniTrace Platform                                  │
│                                                                                        │
│  ┌────────────┐    ┌─────────────┐    ┌──────────────────────────────────────────┐   │
│  │  Anomaly   │───▶│ EventBridge │───▶│         Step Functions Orchestrator       │   │
│  │ Simulator  │    │  (Rule)     │    │  ┌──────────┐ ┌───────────┐ ┌──────────┐ │   │
│  └────────────┘    └─────────────┘    │  │ Auditor  │▶│ Validator │▶│ Patcher  │ │   │
│         ▲               │ DLQ         │  │ (Claude) │ │  (Nova)   │ │  (Nova)  │ │   │
│         │          ┌────▼────┐        │  └──────────┘ └───────────┘ └──────────┘ │   │
│  ┌──────┴──────┐   │   SQS   │        └──────────────────────┬───────────────────┘   │
│  │  API GW     │   │  (DLQ)  │                               │                        │
│  │  REST API   │   └─────────┘                    ┌──────────▼──────────┐             │
│  └──────┬──────┘                                  │      DynamoDB        │             │
│         │                                          │  (Single-Table)     │             │
│  ┌──────▼──────┐                                  └──────────┬──────────┘             │
│  │   React     │                                             │                         │
│  │  Dashboard  │◀────────────────────────────────────────────┘                        │
│  │ (Amplify)   │                                                                       │
│  └─────────────┘                                                                       │
│                                                                                        │
│  Cross-cutting: SNS (notifications + escalation), SSM (remediation), CloudWatch        │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### Component Inventory

| Component | Technology | Purpose |
|---|---|---|
| Anomaly Simulator | AWS Lambda (Python) | Injects synthetic fault events into EventBridge |
| Event Bus | Amazon EventBridge | Routes incident events to Orchestrator |
| Dead-Letter Queue | Amazon SQS | Captures schema-invalid events |
| Orchestrator | AWS Step Functions (Express / Standard) | Sequences Auditor → Validator → Patcher |
| Auditor Agent | AWS Lambda (Python) + Bedrock claude-3-5-sonnet | Root cause analysis |
| Validator Agent | AWS Lambda (Python) + Bedrock nova-pro-v1:0 | Guardrail safety scoring |
| Patcher Agent | AWS Lambda (Python) + Bedrock nova-pro-v1:0 | Remediation generation + execution |
| Incident Store | Amazon DynamoDB (single-table) | Durable incident and trace storage |
| API Layer | Amazon API Gateway REST + Lambda handlers | HTTP interface for Dashboard |
| Dashboard | React + Tailwind CSS + Vite on AWS Amplify | SRE monitoring and approval UI |
| Notifications | Amazon SNS (2 topics: notification, SRE escalation) | Alerts and escalation |
| Remediation Exec | AWS Systems Manager (SSM) | Executes LOW-risk remediation commands |
| Observability | CloudWatch Logs + Metrics + Alarms | Centralised telemetry |
| IAM / Config | AWS IAM + AWS Config rules | Least-privilege enforcement |

---

## Data Models

### DynamoDB Single-Table Schema

**Table name:** `OmniTraceIncidents`

| Attribute | Type | Description |
|---|---|---|
| `IncidentID` | String (PK) | UUID identifying the incident |
| `Timestamp` | String (SK) | ISO-8601 UTC creation time |
| `Status` | String | `OPEN` → `PENDING_APPROVAL` → `RESOLVED` / `FAILED` / `EXECUTION_FAILED` |
| `AgentTraces` | List(Map) | Array of `{executionArn, executionName, agentName, durationMs, status}` |
| `CostSavedINR` | Number | Cost savings in Indian Rupees (0 until resolved) |
| `ExpiresAt` | Number | Unix epoch timestamp = createdAt + 90 days (TTL attribute) |
| `FaultType` | String | `LatencySpike` / `HTTP5xxError` / `MemoryOOM` |
| `RcaPayload` | Map | `{rootCause, confidence, recommendedActions}` from Auditor |
| `RemediationPlan` | Map | `{scriptContent, targetService, riskTier, safetyScore}` from Patcher/Validator |
| `ExecutionArn` | String | Current/last Step Functions execution ARN (for PENDING_APPROVAL resume) |

```
PK: IncidentID (e.g. "INC-20240901-abc123")
SK: Timestamp  (e.g. "2024-09-01T14:23:05Z")
```

### EventBridge Event Schema

```json
{
  "source": "omnitrace.simulator",
  "detail-type": "OmniTraceIncident",
  "detail": {
    "incidentId": "INC-20240901-abc123",
    "faultType": "LatencySpike",
    "timestamp": "2024-09-01T14:23:05Z",
    "severity": "medium",
    "targetService": "checkout-service"
  }
}
```

### Auditor RCA Payload

```json
{
  "rootCause": "Increased p99 latency caused by DB connection pool exhaustion",
  "confidence": 0.87,
  "recommendedActions": [
    "Increase DB connection pool size",
    "Enable connection retry with exponential backoff"
  ]
}
```

### Validator Output

```json
{
  "riskTier": "LOW",
  "safetyScore": 0.91,
  "rationale": "Cache purge is reversible with no data loss risk"
}
```

### Patcher Remediation Plan

```json
{
  "scriptContent": "aws elasticache ... purge-cache ...",
  "targetService": "checkout-service",
  "remediationType": "CachePurge",
  "riskTier": "LOW",
  "safetyScore": 0.91
}
```

### Structured Log Entry

```json
{
  "incidentId": "INC-20240901-abc123",
  "agentName": "Auditor",
  "durationMs": 4210,
  "status": "SUCCESS",
  "errorDetails": null,
  "timestamp": "2024-09-01T14:23:09Z",
  "executionArn": "arn:aws:states:..."
}
```

---

## Components and Interfaces

### 1. Anomaly Simulator Lambda

**Runtime:** Python 3.12  
**Handler:** `simulator.handler`

**Supported event types:** `LatencySpike`, `HTTP5xxError`, `MemoryOOM`  
**Configurable parameters:** `severity` (`low`/`medium`/`high`), `targetService` (string)

```python
VALID_FAULT_TYPES = {"LatencySpike", "HTTP5xxError", "MemoryOOM"}
VALID_SEVERITIES = {"low", "medium", "high"}

def handler(event: dict, context) -> dict:
    """
    Input:
        event.faultType: str        — one of VALID_FAULT_TYPES
        event.severity: str         — one of VALID_SEVERITIES (default "medium")
        event.targetService: str    — target service name (default "unknown")

    Output:
        {"statusCode": 200, "body": {"incidentId": str}}
      or
        {"statusCode": 400, "body": {"error": str}}
    """
    fault_type = event.get("faultType", "")
    severity = event.get("severity", "medium")
    target_service = event.get("targetService", "unknown")

    if fault_type not in VALID_FAULT_TYPES:
        return {"statusCode": 400, "body": {"error": f"Unsupported faultType: {fault_type}"}}

    incident_id = generate_incident_id()
    eb_event = build_eventbridge_event(incident_id, fault_type, severity, target_service)
    put_events_to_eventbridge(eb_event)
    return {"statusCode": 200, "body": {"incidentId": incident_id}}
```

### 2. Step Functions Orchestrator (ASL)

**Type:** Standard Workflow (durable, resumable via `.waitForTaskToken` for MEDIUM approval)

**State machine flow:**

```
CreateIncidentRecord
  → InvokeAuditor             (Task: Lambda, retry 2×, exp backoff)
  → InvokeValidator           (Task: Lambda, retry 2×, exp backoff)
  → InvokePatcher             (Task: Lambda, retry 2×, exp backoff)
  → [Choice on riskTier]
       LOW     → AutoApplyAndNotify → UpdateStatusResolved
       MEDIUM  → WaitForApproval (waitForTaskToken) → UpdateStatusResolved
       HIGH    → EscalateToSRE → UpdateStatusHigh
  → [Catch: all errors → UpdateStatusFailed → NotifyFailure]
```

**ASL Retry configuration (applied to all agent Task states):**

```json
"Retry": [
  {
    "ErrorEquals": ["RetryableException", "Lambda.ServiceException", "Lambda.AWSLambdaException"],
    "IntervalSeconds": 2,
    "MaxAttempts": 2,
    "BackoffRate": 2.0
  }
],
"Catch": [
  {
    "ErrorEquals": ["States.ALL"],
    "Next": "UpdateStatusFailed"
  }
]
```

### 3. Auditor Agent Lambda

**Runtime:** Python 3.12  
**Bedrock model:** `anthropic.claude-3-5-sonnet`  
**Timeout:** 60 seconds

```python
def handler(event: dict, context) -> dict:
    """
    Input (from Step Functions):
        event.incidentId: str
        event.faultType: str
        event.timestamp: str   — ISO-8601 incident time

    Output:
        {
          "incidentId": str,
          "rcaPayload": {
            "rootCause": str,
            "confidence": float,          # [0.0, 1.0]
            "recommendedActions": list[str]
          }
        }

    Raises:
        RetryableException  — on Bedrock API error
    """
    start = now()
    try:
        incident_ts = parse_iso8601(event["timestamp"])
        window_start = incident_ts - timedelta(minutes=15)
        log_events = query_cloudwatch_logs(
            log_group=f"/aws/lambda/{event['faultType']}",
            start_time=window_start,
            end_time=incident_ts
        )
        prompt = build_rca_prompt(event["faultType"], log_events)
        bedrock_response = invoke_bedrock(
            model_id="anthropic.claude-3-5-sonnet",
            prompt=prompt
        )
        rca = parse_rca_response(bedrock_response)          # → {rootCause, confidence, recommendedActions}
        validate_rca_schema(rca)                             # raises ValueError on bad schema
        emit_structured_log("Auditor", event["incidentId"], now() - start, "SUCCESS", None)
        return {"incidentId": event["incidentId"], "rcaPayload": rca}
    except BedrockError as e:
        emit_structured_log("Auditor", event["incidentId"], now() - start, "FAILED", str(e))
        raise RetryableException(str(e))
```

### 4. Validator Agent Lambda

**Runtime:** Python 3.12  
**Bedrock model:** `amazon.nova-pro-v1:0`  
**Timeout:** 45 seconds

```python
def handler(event: dict, context) -> dict:
    """
    Input:
        event.incidentId: str
        event.rcaPayload: dict             — from Auditor
        event.remediationPlan: dict        — draft from Patcher (first pass) or None

    Output:
        {
          "incidentId": str,
          "riskTier": "LOW" | "MEDIUM" | "HIGH",
          "safetyScore": float,            # [0.0, 1.0]
          "validatorRationale": str
        }

    Raises:
        RetryableException  — on Bedrock API error
    """
```

**Risk-tier decision logic:**

```python
def determine_risk_tier(safety_score: float, remediation_type: str) -> str:
    """
    safety_score in [0.0, 1.0]
    remediation_type: str — "CachePurge" | "ContainerRestart" | "ScaleOut" | "Rollback" | "DBChange"
    """
    HIGH_RISK_TYPES = {"Rollback", "DBChange"}
    if remediation_type in HIGH_RISK_TYPES:
        return "HIGH"
    if safety_score >= 0.85:
        return "LOW"
    if safety_score >= 0.60:
        return "MEDIUM"
    return "HIGH"
```

### 5. Patcher Agent Lambda

**Runtime:** Python 3.12  
**Bedrock model:** `amazon.nova-pro-v1:0`  
**Timeout:** 90 seconds

```python
def handler(event: dict, context) -> dict:
    """
    Input:
        event.incidentId: str
        event.rcaPayload: dict
        event.riskTier: "LOW" | "MEDIUM" | "HIGH"
        event.safetyScore: float
        event.taskToken: str | None   — Step Functions task token for MEDIUM approval

    Routing:
        LOW    → execute via SSM → SNS notify
        MEDIUM → write PENDING_APPROVAL to DynamoDB → pause (task token)
        HIGH   → publish to SNS SRE topic → return without execution

    Raises:
        RetryableException      — on Bedrock API error
        RemediationFailedException — on SSM non-zero exit code (LOW path)
    """
```

**SSM execution (LOW path):**

```python
def execute_via_ssm(script: str, target_service: str, incident_id: str) -> None:
    response = ssm_client.send_command(
        Targets=[{"Key": "tag:Service", "Values": [target_service]}],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script]},
        Comment=f"OmniTrace remediation for {incident_id}"
    )
    command_id = response["Command"]["CommandId"]
    result = wait_for_ssm_command(command_id)   # polls until terminal state
    if result["StatusDetails"] != "Success":
        update_dynamodb_status(incident_id, "EXECUTION_FAILED")
        raise RemediationFailedException(f"SSM exit code non-zero for {incident_id}")
```

### 6. API Gateway + Lambda Handlers

**API structure:**

```
GET  /incidents                      → list_incidents_handler
GET  /incidents/{incidentId}         → get_incident_handler
POST /incidents/{incidentId}/approve → approve_incident_handler
POST /simulator/inject               → simulator_handler (wraps Simulator Lambda)
```

**list_incidents_handler:**

```python
def list_incidents_handler(event: dict, context) -> dict:
    """
    Query params: pageSize (default 20), nextToken (pagination)
    Returns:
        {
          "items": list[IncidentSummary],
          "nextToken": str | null
        }
    """
    page_size = int(event.get("queryStringParameters", {}).get("pageSize", 20))
    next_token = event.get("queryStringParameters", {}).get("nextToken")
    result = dynamodb_scan_incidents(page_size=page_size, exclusive_start_key=decode_token(next_token))
    return ok({"items": result.items, "nextToken": encode_token(result.last_evaluated_key)})
```

**approve_incident_handler:**

```python
def approve_incident_handler(event: dict, context) -> dict:
    """
    Path param: incidentId
    Behavior:
        1. Fetch incident from DynamoDB.
        2. If Status != PENDING_APPROVAL → return HTTP 409.
        3. Send task success to Step Functions using stored taskToken.
        4. Return HTTP 200.
    """
    incident_id = event["pathParameters"]["incidentId"]
    incident = get_incident(incident_id)
    if incident is None:
        return not_found(f"Incident {incident_id} not found")
    if incident["Status"] != "PENDING_APPROVAL":
        return conflict(f"Incident {incident_id} is not awaiting approval; current status: {incident['Status']}")
    sfn_client.send_task_success(
        taskToken=incident["TaskToken"],
        output=json.dumps({"approved": True, "approvedBy": get_caller_identity(event)})
    )
    return ok({"message": "Approval submitted"})
```

### 7. React Dashboard

**Tech stack:** React 18, Tailwind CSS 3, Vite 5  
**Deployment:** AWS Amplify Hosting (CI/CD from `main` branch)

**Component tree:**

```
App
├── IncidentTable          — lists all incidents, auto-polls every 10 s
│   └── IncidentRow        — shows ID, Timestamp, Status, CostSavedINR
│       └── ApproveButton  — rendered only when Status === "PENDING_APPROVAL"
├── IncidentDetail         — full record including AgentTraces
│   ├── RcaPanel           — rootCause + confidence visualisation
│   └── RemediationPanel   — remediation plan + risk tier badge
├── CostSavingsSummary     — aggregate INR savings for current calendar month
└── ErrorBanner            — shown on any non-2xx API response
```

**Data fetching hook (abbreviated):**

```typescript
// hooks/useIncidents.ts
export function useIncidents(pageSize = 20) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetch = async () => {
      try {
        const res = await api.get(`/incidents?pageSize=${pageSize}`);
        setIncidents(res.data.items);
        setError(null);
      } catch (err) {
        setError(extractErrorMessage(err));   // always a human-readable string
      }
    };
    fetch();
    const id = setInterval(fetch, 10_000);   // poll every 10 s
    return () => clearInterval(id);
  }, [pageSize]);

  return { incidents, error };
}
```

**Monthly cost aggregation:**

```typescript
// utils/costAggregation.ts
export function sumMonthlyCostINR(incidents: Incident[]): number {
  const now = new Date();
  return incidents
    .filter(i => i.status === "RESOLVED")
    .filter(i => {
      const ts = new Date(i.timestamp);
      return ts.getFullYear() === now.getFullYear() && ts.getMonth() === now.getMonth();
    })
    .reduce((sum, i) => sum + (i.costSavedINR ?? 0), 0);
}
```

### 8. DynamoDB Operations

```python
# dynamodb/operations.py

def create_incident_record(incident_id: str, timestamp: str, fault_type: str) -> None:
    """Creates the initial OPEN record."""
    expires_at = compute_ttl(timestamp, days=90)
    table.put_item(Item={
        "IncidentID": incident_id,
        "Timestamp": timestamp,
        "Status": "OPEN",
        "AgentTraces": [],
        "CostSavedINR": 0,
        "FaultType": fault_type,
        "ExpiresAt": expires_at
    })

def update_incident_status(incident_id: str, timestamp: str, status: str) -> None:
    table.update_item(
        Key={"IncidentID": incident_id, "Timestamp": timestamp},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":s": status}
    )

def append_agent_trace(incident_id: str, timestamp: str, trace: dict) -> None:
    """Appends a trace entry to the AgentTraces list."""
    table.update_item(
        Key={"IncidentID": incident_id, "Timestamp": timestamp},
        UpdateExpression="SET AgentTraces = list_append(AgentTraces, :t)",
        ExpressionAttributeValues={":t": [trace]}
    )

def compute_ttl(iso_timestamp: str, days: int) -> int:
    """Returns Unix epoch = parsed(iso_timestamp) + days."""
    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return int((dt + timedelta(days=days)).timestamp())
```

### 9. Observability Helpers

```python
# observability/telemetry.py

def emit_structured_log(agent_name: str, incident_id: str,
                         duration_ms: float, status: str,
                         error_details: str | None) -> None:
    """Writes a JSON-structured log entry to stdout (captured by CloudWatch)."""
    entry = {
        "incidentId": incident_id,
        "agentName": agent_name,
        "durationMs": round(duration_ms),
        "status": status,
        "errorDetails": error_details
    }
    print(json.dumps(entry))

def publish_resolution_metrics(incident_id: str,
                                resolution_time_ms: float,
                                cost_saved_inr: float) -> None:
    """Publishes IncidentResolutionTimeMs and RemediationCostSavedINR to CloudWatch."""
    cw.put_metric_data(
        Namespace="OmniTrace",
        MetricData=[
            {
                "MetricName": "IncidentResolutionTimeMs",
                "Value": resolution_time_ms,
                "Unit": "Milliseconds",
                "Dimensions": [{"Name": "IncidentID", "Value": incident_id}]
            },
            {
                "MetricName": "RemediationCostSavedINR",
                "Value": cost_saved_inr,
                "Unit": "None",
                "Dimensions": [{"Name": "IncidentID", "Value": incident_id}]
            }
        ]
    )
```

---

## IAM Role Summary

| Role | Allows | Denies (implicit) |
|---|---|---|
| `OmniTrace-Auditor-Role` | `logs:FilterLogEvents`, `logs:DescribeLogGroups`, `bedrock:InvokeModel` (claude-3-5-sonnet ARN only) | All other Bedrock models, DynamoDB, SSM, SNS |
| `OmniTrace-Validator-Role` | `dynamodb:GetItem`, `bedrock:InvokeModel` (nova-pro ARN only) | All other Bedrock models, SSM, SNS |
| `OmniTrace-Patcher-Role` | `dynamodb:PutItem`, `dynamodb:UpdateItem`, `bedrock:InvokeModel` (nova-pro ARN only), `sns:Publish` (both topics), `ssm:SendCommand` (tagged resources) | Other DynamoDB tables, other Bedrock models |
| `OmniTrace-Orchestrator-Role` | `lambda:InvokeFunction` (Auditor/Validator/Patcher only), `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `states:SendTaskSuccess` | All other services |
| `OmniTrace-APIHandler-Role` | `dynamodb:Scan`, `dynamodb:GetItem`, `dynamodb:UpdateItem`, `states:SendTaskSuccess`, `states:DescribeExecution` | SNS, SSM, Bedrock |

---

## Error Handling

| Error Source | Handling |
|---|---|
| Bedrock API error (any agent) | Raise `RetryableException` → Step Functions retries ×2 with exponential backoff |
| Step Functions all-retries exhausted | Transition to `UpdateStatusFailed` → DynamoDB `FAILED`, SNS failure notification |
| SSM non-zero exit (LOW path) | DynamoDB `EXECUTION_FAILED`, raise `RemediationFailedException` → failure path |
| EventBridge schema validation failure | SQS dead-letter queue + CloudWatch log |
| API Gateway unhandled Lambda exception | HTTP 500 + generic message + CloudWatch log |
| API 409 (approve non-PENDING) | HTTP 409 with descriptive body |
| Dashboard API non-2xx | `ErrorBanner` component renders human-readable message |
| AWS Config IAM scope violation | SNS notification to ops topic |

---

## Sequence Diagram — Happy Path (LOW risk)

```
SRE/Simulator → EventBridge → Step Functions:
  1. Simulator.handler() publishes EventBridge event
  2. EventBridge rule matches → triggers Step Functions execution
  3. Orchestrator: CreateIncidentRecord → DynamoDB (Status=OPEN)
  4. Orchestrator: InvokeAuditor → Auditor.handler()
       Auditor queries CloudWatch Logs (15-min window)
       Auditor invokes Bedrock claude-3-5-sonnet → RCA payload
       Auditor returns {incidentId, rcaPayload}
  5. Orchestrator: InvokeValidator → Validator.handler()
       Validator invokes Bedrock nova-pro-v1:0 → {riskTier=LOW, safetyScore=0.93}
  6. Orchestrator: InvokePatcher → Patcher.handler()
       Patcher invokes Bedrock nova-pro-v1:0 → remediation script
       Patcher executes via SSM → Success
       Patcher publishes SNS notification
  7. Orchestrator: UpdateStatusResolved → DynamoDB (Status=RESOLVED, CostSavedINR=...)
  8. Orchestrator: publish_resolution_metrics() → CloudWatch
```

## Testing Strategy

**Dual Testing Approach:**
- **Unit / Property tests**: Verify universal properties using a property-based testing library (e.g., Hypothesis for Python, fast-check for TypeScript). Each property in the Correctness Properties section should be implemented as a property test with a minimum of 100 randomised iterations.
- **Example-based unit tests**: Verify specific scenarios (happy-path, error paths, model ID assertions) with concrete, deterministic inputs.
- **Integration tests**: Verify infrastructure wiring — EventBridge routing, Step Functions execution, CloudWatch metric delivery, SNS delivery. Use 1–3 representative examples per criterion.
- **Smoke tests**: Verify one-time configuration (DynamoDB PITR, TTL attribute, IAM role existence, Amplify deployment).

**Agent Lambda testing:**
- Mock the Bedrock `invoke_model` client using `unittest.mock` or `moto`. This keeps tests fast, deterministic, and cost-free.
- Mock SSM `send_command` for Patcher unit tests.
- Mock DynamoDB using `moto` for DynamoDB-touching tests.

**Frontend testing:**
- Use `vitest` + `@testing-library/react` for component property tests.
- Mock `fetch`/`axios` to return controlled responses for error-path tests.

**Property test tag format:**
```
Feature: omnitrace, Property {N}: {property_title}
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

**Property Reflection Summary:**
Properties 5.2/5.3/5.4/7.5 (risk-tier routing) are consolidated into Property 7. Properties 6.2/6.3 (DynamoDB lifecycle) are consolidated into Property 8. Properties 11.2/11.4 (metrics) are consolidated into Property 13. All other properties are kept distinct as they cover different components or schemas.

### Property 1: EventBridge event schema enforcement

*For any* object submitted to the OmniTrace event schema validator, the validator SHALL accept the object if and only if it contains all five required fields (`source`, `detail-type`, `detail.incidentId`, `detail.faultType`, `detail.timestamp`), and SHALL reject any object missing one or more of those fields.

**Validates: Requirements 1.1**

---

### Property 2: Orchestrator retry count

*For any* agent Lambda that always throws a `RetryableException`, the Step Functions execution SHALL invoke that Lambda exactly 3 times (1 initial + 2 retries) before transitioning to the failure state.

**Validates: Requirements 2.2**

---

### Property 3: Agent trace persistence

*For any* Step Functions execution (successful or failed), the DynamoDB Incident record's `AgentTraces` list SHALL contain at least one entry with a non-null `executionArn` and `executionName`.

**Validates: Requirements 2.5**

---

### Property 4: Auditor 15-minute log window

*For any* incident timestamp T, the CloudWatch Logs query issued by the Auditor SHALL use a start time of exactly T − 15 minutes and an end time of T.

**Validates: Requirements 3.1**

---

### Property 5: Auditor RCA output schema

*For any* mocked Bedrock response, the Auditor's `parse_rca_response` function SHALL return a dict containing `rootCause` (non-empty string), `confidence` (float in [0.0, 1.0]), and `recommendedActions` (non-empty list of strings).

**Validates: Requirements 3.3**

---

### Property 6: Validator output schema

*For any* mocked Bedrock response to the Validator, the Validator SHALL return a payload where `riskTier` is one of `{LOW, MEDIUM, HIGH}` and `safetyScore` is a float in [0.0, 1.0].

**Validates: Requirements 4.3**

---

### Property 7: Patcher risk-tier routing invariant

*For any* incident with `riskTier = LOW`: SSM `SendCommand` SHALL be called and SNS notification SHALL be published, and the incident SHALL NOT remain in `PENDING_APPROVAL`.  
*For any* incident with `riskTier = MEDIUM`: DynamoDB Status SHALL be `PENDING_APPROVAL`, SSM `SendCommand` SHALL NOT be called.  
*For any* incident with `riskTier = HIGH`: SNS SRE escalation SHALL be published containing `incidentId`, `rcaSummary`, and `remediationDetails`, and SSM `SendCommand` SHALL NOT be called.

**Validates: Requirements 5.2, 5.3, 5.4, 7.4, 7.5**

---

### Property 8: Incident DynamoDB lifecycle

*For any* valid EventBridge incident event, the created DynamoDB record SHALL have `Status = OPEN`, `AgentTraces = []`, and `CostSavedINR = 0` at creation time.  
*For any* incident that transitions to `RESOLVED`, the DynamoDB record SHALL have `Status = RESOLVED` and `CostSavedINR` as a non-negative numeric value.

**Validates: Requirements 6.2, 6.3**

---

### Property 9: TTL is always 90 days from creation

*For any* ISO-8601 creation timestamp T, the `compute_ttl` function SHALL return a Unix epoch value equal to T + exactly 90 days (within ±1 second for integer rounding).

**Validates: Requirements 6.5**

---

### Property 10: Simulator schema correctness

*For any* supported `faultType` value in `{LatencySpike, HTTP5xxError, MemoryOOM}`, the `build_eventbridge_event` function SHALL produce an event containing all five required schema fields with the correct `faultType`, `severity`, and `targetService` values from the input.

**Validates: Requirements 10.3, 10.5**

---

### Property 11: Simulator rejects invalid fault types

*For any* string not in `VALID_FAULT_TYPES`, the Simulator SHALL return `statusCode = 400` and SHALL NOT invoke `put_events_to_eventbridge`.

**Validates: Requirements 10.4**

---

### Property 12: Structured log schema

*For any* Lambda invocation (success or failure), the `emit_structured_log` function SHALL produce a JSON-serialisable dict containing all five required fields: `incidentId`, `agentName`, `durationMs` (integer ≥ 0), `status`, and `errorDetails`.

**Validates: Requirements 11.1**

---

### Property 13: CloudWatch metric publication

*For any* resolved incident with `resolution_time_ms` and `cost_saved_inr`, the `publish_resolution_metrics` function SHALL invoke `put_metric_data` with both `IncidentResolutionTimeMs` and `RemediationCostSavedINR` metrics carrying the correct values.

**Validates: Requirements 11.2, 11.4**

---

### Property 14: Dashboard approval button rendered for PENDING_APPROVAL

*For any* incident record with `Status = PENDING_APPROVAL`, the rendered `IncidentRow` component SHALL include an `ApproveButton` element; for any incident with any other `Status` value, no `ApproveButton` SHALL be rendered.

**Validates: Requirements 7.2, 8.3**

---

### Property 15: Dashboard agent trace display

*For any* incident record containing `rcaPayload.rootCause` and `rcaPayload.confidence` values, the rendered `RcaPanel` component SHALL include both values in its output.

**Validates: Requirements 8.4**

---

### Property 16: Monthly cost aggregation correctness

*For any* list of incident records where some are `RESOLVED` in the current calendar month and others are not (different month, different status), the `sumMonthlyCostINR` function SHALL return exactly the sum of `CostSavedINR` for the `RESOLVED` current-month incidents only.

**Validates: Requirements 8.5**

---

### Property 17: Dashboard error banner on non-2xx response

*For any* HTTP error response (status code 4xx or 5xx) from the API, the `useIncidents` hook SHALL set a non-null, non-empty `error` string, and the rendered `ErrorBanner` component SHALL be visible with that message.

**Validates: Requirements 8.7**

---

### Property 18: API GET /incidents/{id} includes AgentTraces

*For any* incident stored in DynamoDB with a non-empty `AgentTraces` list, a `GET /incidents/{incidentId}` request SHALL return a response body containing an `AgentTraces` field with all stored trace entries.

**Validates: Requirements 9.2**

---

### Property 19: API 409 on non-PENDING_APPROVAL approve

*For any* incident whose `Status` is not `PENDING_APPROVAL`, a `POST /incidents/{incidentId}/approve` request SHALL return HTTP 409 with a body describing the conflict, and SHALL NOT call `sfn_client.send_task_success`.

**Validates: Requirements 9.4**
