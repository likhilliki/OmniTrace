# Implementation Plan: OmniTrace

## Overview

OmniTrace is built in three layers: infrastructure-as-code (CDK), a Python 3.12 Lambda backend, and a React/Tailwind/Vite frontend on AWS Amplify. Tasks follow the dependency order: IaC scaffolding → shared utilities → individual agents → orchestration wiring → API layer → frontend → observability hardening → testing.

---

## Tasks

- [ ] 1. Project scaffolding and IaC foundation
  - [x] 1.1 Initialise CDK app and define stack structure
    - Create `cdk/` directory with `app.py` and a single `OmniTraceStack`
    - Add `cdk.json`, `requirements.txt` (CDK deps), and `.gitignore`
    - Define shared constants (stack name, region, account) in `cdk/constants.py`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 1.2 Define DynamoDB table construct
    - Create `OmniTraceIncidents` table with `IncidentID` (PK, String) and `Timestamp` (SK, String)
    - Enable PITR (`point_in_time_recovery=True`)
    - Set TTL attribute to `ExpiresAt`
    - _Requirements: 6.1, 6.4, 6.5_

  - [x] 1.3 Define SNS topics and SQS dead-letter queue
    - Create SNS topic `OmniTrace-Notifications` (general notification)
    - Create SNS topic `OmniTrace-SRE-Escalation` (SRE escalation)
    - Create SQS queue `OmniTrace-EventBridge-DLQ` for failed EventBridge events
    - _Requirements: 2.4, 5.4, 7.1, 7.4, 11.3_

  - [-] 1.4 Define EventBridge rule with DLQ
    - Create EventBridge rule matching `source = "omnitrace.simulator"` and `detail-type = "OmniTraceIncident"`
    - Set dead-letter queue to `OmniTrace-EventBridge-DLQ`
    - Wire rule target to the Step Functions state machine (added in task 3.1)
    - _Requirements: 1.1, 1.3, 1.4_

  - [x] 1.5 Define least-privilege IAM roles for all Lambda functions
    - `OmniTrace-Auditor-Role`: `logs:FilterLogEvents`, `logs:DescribeLogGroups`, `bedrock:InvokeModel` scoped to `claude-3-5-sonnet` ARN only
    - `OmniTrace-Validator-Role`: `dynamodb:GetItem`, `bedrock:InvokeModel` scoped to `nova-pro-v1:0` ARN only
    - `OmniTrace-Patcher-Role`: `dynamodb:PutItem`, `dynamodb:UpdateItem`, `bedrock:InvokeModel` (nova-pro), `sns:Publish` (both topics), `ssm:SendCommand` scoped to tagged resources
    - `OmniTrace-APIHandler-Role`: `dynamodb:Scan`, `dynamodb:GetItem`, `dynamodb:UpdateItem`, `states:SendTaskSuccess`, `states:DescribeExecution`
    - `OmniTrace-Orchestrator-Role`: `lambda:InvokeFunction` (three agent ARNs only), `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `states:SendTaskSuccess`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [-] 1.6 Define AWS Config rule for IAM drift detection
    - Add AWS Config managed rule `iam-policy-no-statements-with-admin-access` or a custom Lambda-backed rule that alerts when any OmniTrace IAM role gains permissions outside its defined scope
    - Wire Config rule non-compliance notification to `OmniTrace-Notifications` SNS topic
    - _Requirements: 12.6_

- [ ] 2. Shared Python utilities
  - [-] 2.1 Implement DynamoDB operations module
    - Create `lambdas/shared/dynamodb/operations.py`
    - Implement `create_incident_record(incident_id, timestamp, fault_type)` — writes `Status=OPEN`, `AgentTraces=[]`, `CostSavedINR=0`, `ExpiresAt=compute_ttl(timestamp, 90)`
    - Implement `update_incident_status(incident_id, timestamp, status)`
    - Implement `append_agent_trace(incident_id, timestamp, trace: dict)`
    - Implement `compute_ttl(iso_timestamp, days) -> int`
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [ ]* 2.2 Write property test for `compute_ttl` (Property 9)
    - **Property 9: TTL is always 90 days from creation**
    - **Validates: Requirements 6.5**
    - Use `hypothesis` with `st.datetimes()` to verify `compute_ttl(T, 90)` returns `int(T + 90 days)` within ±1 second for any valid ISO-8601 timestamp

  - [-] 2.3 Implement observability telemetry module
    - Create `lambdas/shared/observability/telemetry.py`
    - Implement `emit_structured_log(agent_name, incident_id, duration_ms, status, error_details)` — prints JSON to stdout
    - Implement `publish_resolution_metrics(incident_id, resolution_time_ms, cost_saved_inr)` — calls `cloudwatch.put_metric_data` with both `IncidentResolutionTimeMs` and `RemediationCostSavedINR`
    - _Requirements: 11.1, 11.2, 11.4_

  - [ ]* 2.4 Write property test for `emit_structured_log` (Property 12)
    - **Property 12: Structured log schema**
    - **Validates: Requirements 11.1**
    - Use `hypothesis` with varied `agent_name`, `incident_id`, `duration_ms`, `status` to verify JSON-serialisable output containing all five required fields with `durationMs >= 0`

  - [ ]* 2.5 Write property test for `publish_resolution_metrics` (Property 13)
    - **Property 13: CloudWatch metric publication**
    - **Validates: Requirements 11.2, 11.4**
    - Use `hypothesis` with arbitrary `resolution_time_ms` and `cost_saved_inr` floats; mock `put_metric_data`; verify both metric names and correct values appear in the call

  - [ ] 2.6 Implement EventBridge event schema validator
    - Create `lambdas/shared/validation/event_schema.py`
    - Implement `validate_event(event: dict) -> bool` — returns `True` iff all five fields (`source`, `detail-type`, `detail.incidentId`, `detail.faultType`, `detail.timestamp`) are present and non-empty
    - _Requirements: 1.1, 1.3_

  - [ ]* 2.7 Write property test for EventBridge schema validator (Property 1)
    - **Property 1: EventBridge event schema enforcement**
    - **Validates: Requirements 1.1**
    - Use `hypothesis` to generate dicts with random subsets of required fields; verify `validate_event` returns `True` only for complete events and `False` for any with a missing field

- [~] 3. Checkpoint — shared utilities baseline
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Anomaly Simulator Lambda
  - [~] 4.1 Implement simulator handler
    - Create `lambdas/simulator/simulator.py` with `VALID_FAULT_TYPES`, `VALID_SEVERITIES`, `handler(event, context)`
    - Implement `generate_incident_id()` returning `INC-{date}-{uuid6}`
    - Implement `build_eventbridge_event(incident_id, fault_type, severity, target_service)` producing the canonical EventBridge payload
    - Implement `put_events_to_eventbridge(eb_event)` calling `boto3` EventBridge `put_events`
    - Return HTTP 400 for invalid `faultType`; HTTP 200 with `incidentId` on success
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 4.2 Write property test for `build_eventbridge_event` (Property 10)
    - **Property 10: Simulator schema correctness**
    - **Validates: Requirements 10.3, 10.5**
    - Use `hypothesis` with `st.sampled_from(VALID_FAULT_TYPES)`, `st.sampled_from(VALID_SEVERITIES)`, `st.text()` for `targetService`; verify all five schema fields present with correct values

  - [ ]* 4.3 Write property test for Simulator invalid fault type rejection (Property 11)
    - **Property 11: Simulator rejects invalid fault types**
    - **Validates: Requirements 10.4**
    - Use `hypothesis` with `st.text().filter(lambda s: s not in VALID_FAULT_TYPES)`; mock `put_events_to_eventbridge`; verify `statusCode = 400` and mock not called

  - [~] 4.4 Add Simulator Lambda CDK construct
    - Add `aws_lambda.Function` for Simulator in `OmniTraceStack`
    - Grant `events:PutEvents` permission on the OmniTrace event bus
    - Expose via `POST /simulator/inject` on API Gateway (wired in task 8)
    - _Requirements: 10.1_

- [ ] 5. Step Functions Orchestrator
  - [~] 5.1 Author ASL state machine definition
    - Create `statemachine/omnitrace_asl.json`
    - States: `CreateIncidentRecord` (Lambda task — calls DynamoDB create via a thin Lambda or SDK integration) → `InvokeAuditor` → `InvokeValidator` → `InvokePatcher` → `RiskTierChoice` → branches: `AutoApplyAndNotify` (LOW), `WaitForApproval` (MEDIUM, `waitForTaskToken`), `EscalateToSRE` (HIGH) → `UpdateStatusResolved`
    - Add `Catch: States.ALL → UpdateStatusFailed → NotifyFailure` on all agent tasks
    - Add `Retry` on all agent tasks: `ErrorEquals: [RetryableException, Lambda.ServiceException, Lambda.AWSLambdaException]`, `MaxAttempts: 2`, `IntervalSeconds: 2`, `BackoffRate: 2.0`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [~] 5.2 Add Step Functions CDK construct
    - Create `aws_stepfunctions.StateMachine` (Standard type) in `OmniTraceStack` using the ASL definition from 5.1
    - Attach `OmniTrace-Orchestrator-Role`
    - Set execution history retention to 90 days
    - Wire as EventBridge rule target (completing task 1.4)
    - _Requirements: 2.6, 11.5_

  - [ ]* 5.3 Write property test for Orchestrator retry count (Property 2)
    - **Property 2: Orchestrator retry count**
    - **Validates: Requirements 2.2**
    - Use `hypothesis` with `st.sampled_from(["Auditor", "Validator", "Patcher"])`; stub the agent Lambda to always raise `RetryableException`; use Step Functions Local or mocked SDK to verify exactly 3 invocations before failure state

- [ ] 6. Auditor Agent Lambda
  - [~] 6.1 Implement Auditor handler
    - Create `lambdas/auditor/auditor.py`
    - Implement `query_cloudwatch_logs(log_group, start_time, end_time)` using `boto3` CloudWatch Logs `filter_log_events`
    - Implement `build_rca_prompt(fault_type, log_events) -> str`
    - Implement `invoke_bedrock(model_id, prompt)` calling Bedrock `invoke_model` with `anthropic.claude-3-5-sonnet`
    - Implement `parse_rca_response(bedrock_response) -> dict` extracting `{rootCause, confidence, recommendedActions}`
    - Implement `validate_rca_schema(rca)` raising `ValueError` on invalid schema
    - Raise `RetryableException` on `BedrockError`; call `emit_structured_log` on both success and failure
    - Enforce 60-second Lambda timeout in CDK construct
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 6.2 Write property test for `parse_rca_response` (Property 5)
    - **Property 5: Auditor RCA output schema**
    - **Validates: Requirements 3.3**
    - Use `hypothesis` with `st.text()` for `rootCause`, `st.floats(0.0, 1.0)` for `confidence`, `st.lists(st.text(), min_size=1)` for `recommendedActions`; build mock Bedrock responses; verify `parse_rca_response` always returns a valid schema

  - [ ]* 6.3 Write property test for Auditor 15-minute log window (Property 4)
    - **Property 4: Auditor 15-minute log window**
    - **Validates: Requirements 3.1**
    - Use `hypothesis` with `st.datetimes()` for incident timestamp T; mock `filter_log_events`; verify query `start_time = T − 15 min` and `end_time = T` exactly

  - [~] 6.4 Add Auditor Lambda CDK construct
    - Add `aws_lambda.Function` with runtime Python 3.12, timeout 60 s, `OmniTrace-Auditor-Role`
    - _Requirements: 3.5, 12.1_

- [ ] 7. Validator Agent Lambda
  - [~] 7.1 Implement Validator handler
    - Create `lambdas/validator/validator.py`
    - Implement `invoke_bedrock(model_id, prompt)` calling `amazon.nova-pro-v1:0`
    - Implement `determine_risk_tier(safety_score, remediation_type) -> str` with HIGH_RISK_TYPES set, thresholds at 0.85 (LOW) and 0.60 (MEDIUM)
    - Return `{incidentId, riskTier, safetyScore, validatorRationale}`
    - Raise `RetryableException` on `BedrockError`; call `emit_structured_log`
    - Enforce 45-second Lambda timeout
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 7.2 Write property test for Validator output schema (Property 6)
    - **Property 6: Validator output schema**
    - **Validates: Requirements 4.3**
    - Use `hypothesis` to generate mocked Bedrock responses with varied `safetyScore` and `remediationType`; verify `riskTier ∈ {LOW, MEDIUM, HIGH}` and `safetyScore ∈ [0.0, 1.0]` for all inputs

  - [~] 7.3 Add Validator Lambda CDK construct
    - Add `aws_lambda.Function` with runtime Python 3.12, timeout 45 s, `OmniTrace-Validator-Role`
    - _Requirements: 4.5, 12.3_

- [ ] 8. Patcher Agent Lambda
  - [~] 8.1 Implement Patcher handler — remediation generation
    - Create `lambdas/patcher/patcher.py`
    - Implement `invoke_bedrock(model_id, prompt)` calling `amazon.nova-pro-v1:0` to generate `scriptContent`
    - Build `RemediationPlan` dict `{scriptContent, targetService, remediationType, riskTier, safetyScore}`
    - _Requirements: 5.1_

  - [~] 8.2 Implement Patcher LOW-risk SSM execution path
    - Implement `execute_via_ssm(script, target_service, incident_id)` — `ssm.send_command` with tag-based targets, poll `wait_for_ssm_command`, raise `RemediationFailedException` on non-zero exit
    - On success: call `update_incident_status` to `RESOLVED`, publish SNS notification, call `publish_resolution_metrics`
    - On `RemediationFailedException`: call `update_dynamodb_status(incident_id, "EXECUTION_FAILED")`
    - _Requirements: 5.2, 5.5, 7.1_

  - [~] 8.3 Implement Patcher MEDIUM-risk approval path
    - Write `PENDING_APPROVAL` status and `TaskToken` to DynamoDB; do NOT execute SSM
    - _Requirements: 5.3, 7.2, 7.3_

  - [~] 8.4 Implement Patcher HIGH-risk escalation path
    - Publish to `OmniTrace-SRE-Escalation` SNS topic with `incidentId`, `rcaSummary`, and `remediationDetails`; do NOT execute SSM
    - _Requirements: 5.4, 7.4, 7.5_

  - [ ]* 8.5 Write property test for Patcher risk-tier routing (Property 7)
    - **Property 7: Patcher risk-tier routing invariant**
    - **Validates: Requirements 5.2, 5.3, 5.4, 7.4, 7.5**
    - Use `hypothesis` with `st.sampled_from(["LOW", "MEDIUM", "HIGH"])`; mock `ssm_client`, `sns_client`, `dynamodb`; verify for each tier: correct calls made and forbidden calls not made

  - [~] 8.6 Add Patcher Lambda CDK construct
    - Add `aws_lambda.Function` with runtime Python 3.12, timeout 90 s, `OmniTrace-Patcher-Role`
    - _Requirements: 5.6, 12.2_

- [~] 9. Checkpoint — agent pipeline complete
  - Ensure all agent tests pass and the ASL state machine references correct Lambda ARNs, ask the user if questions arise.

- [ ] 10. API Gateway and Lambda handlers
  - [~] 10.1 Implement `list_incidents_handler`
    - Create `lambdas/api/list_incidents.py`
    - Parse `pageSize` (default 20) and `nextToken` query params
    - Call `dynamodb_scan_incidents(page_size, exclusive_start_key)`; encode/decode pagination token
    - Return `{"items": [...], "nextToken": str | null}` with HTTP 200
    - Log unhandled exceptions and return HTTP 500 with generic message
    - _Requirements: 9.1, 9.6_

  - [~] 10.2 Implement `get_incident_handler`
    - Create `lambdas/api/get_incident.py`
    - Fetch full record by `incidentId` from DynamoDB including `AgentTraces`
    - Return HTTP 200 with full record, or HTTP 404 if not found
    - _Requirements: 9.2_

  - [ ]* 10.3 Write property test for `GET /incidents/{id}` AgentTraces inclusion (Property 18)
    - **Property 18: API GET /incidents/{id} includes AgentTraces**
    - **Validates: Requirements 9.2**
    - Use `hypothesis` with `st.lists(st.fixed_dictionaries({...}), min_size=1)` for `AgentTraces`; mock DynamoDB `get_item`; verify response body contains all stored trace entries

  - [~] 10.4 Implement `approve_incident_handler`
    - Create `lambdas/api/approve_incident.py`
    - Fetch incident; if `Status != PENDING_APPROVAL` return HTTP 409 with descriptive body
    - Call `sfn_client.send_task_success(taskToken=..., output=...)` and return HTTP 200
    - _Requirements: 9.3, 9.4_

  - [ ]* 10.5 Write property test for API 409 on non-PENDING_APPROVAL approve (Property 19)
    - **Property 19: API 409 on non-PENDING_APPROVAL approve**
    - **Validates: Requirements 9.4**
    - Use `hypothesis` with `st.sampled_from(["OPEN", "RESOLVED", "FAILED", "EXECUTION_FAILED", "HIGH"])`; mock DynamoDB; verify HTTP 409 and `send_task_success` not called for all non-PENDING statuses

  - [~] 10.6 Define API Gateway REST API CDK construct
    - Create `api/omnitrace_api_stack.py` (or inline in `OmniTraceStack`)
    - Define resources: `GET /incidents`, `GET /incidents/{incidentId}`, `POST /incidents/{incidentId}/approve`, `POST /simulator/inject`
    - Attach Cognito User Pool authorizer (or IAM auth) on all routes
    - Enable CloudWatch access logging and X-Ray tracing
    - Return HTTP 401 for unauthenticated requests; configure GatewayResponse for `DEFAULT_5XX` returning generic message + CloudWatch log
    - _Requirements: 9.1, 9.3, 9.5, 9.6_

- [ ] 11. Incident lifecycle wiring
  - [~] 11.1 Implement `CreateIncidentRecord` state integration
    - Add a thin `lambdas/orchestrator_helpers/create_record.py` Lambda (or use SDK integration in ASL) that calls `create_incident_record` and writes initial DynamoDB row
    - Wire as first state in the ASL (completing task 5.1 Step 1)
    - _Requirements: 6.2_

  - [~] 11.2 Implement `UpdateStatusResolved` and `UpdateStatusFailed` states
    - Add `lambdas/orchestrator_helpers/update_status.py` handling both `RESOLVED` and `FAILED` transitions, updating `Status` and `CostSavedINR` (for RESOLVED), calling `publish_resolution_metrics`
    - _Requirements: 2.3, 2.4, 6.3, 11.2, 11.4_

  - [ ]* 11.3 Write property test for Incident DynamoDB lifecycle (Property 8)
    - **Property 8: Incident DynamoDB lifecycle**
    - **Validates: Requirements 6.2, 6.3**
    - Use `hypothesis` to generate valid EventBridge events; mock DynamoDB; verify initial record has `Status=OPEN`, `AgentTraces=[]`, `CostSavedINR=0`; simulate resolution and verify `Status=RESOLVED`, `CostSavedINR >= 0`

  - [ ]* 11.4 Write property test for Agent trace persistence (Property 3)
    - **Property 3: Agent trace persistence**
    - **Validates: Requirements 2.5**
    - Use `hypothesis` with `st.booleans()` for success/failure; mock Step Functions execution; verify `AgentTraces` list in DynamoDB has at least one entry with non-null `executionArn` and `executionName`

- [ ] 12. React + Tailwind + Vite Dashboard
  - [~] 12.1 Initialise frontend project
    - Run `npm create vite@latest frontend -- --template react-ts` inside `frontend/`
    - Install `tailwindcss`, `postcss`, `autoprefixer`; run `npx tailwindcss init -p`
    - Configure `tailwind.config.js` content paths and add Tailwind directives to `index.css`
    - Install `axios` for API calls
    - _Requirements: 8.1, 8.6_

  - [~] 12.2 Implement API client and `useIncidents` hook
    - Create `frontend/src/api/client.ts` with `axios` base URL from env var `VITE_API_BASE_URL`
    - Create `frontend/src/hooks/useIncidents.ts` polling `GET /incidents` every 10 s; set `error` string on non-2xx responses
    - Create `frontend/src/types/incident.ts` TypeScript interface matching DynamoDB schema
    - _Requirements: 8.2, 8.7_

  - [~] 12.3 Implement `IncidentTable` and `IncidentRow` components
    - Create `frontend/src/components/IncidentTable.tsx` listing all incidents with `IncidentID`, `Timestamp`, `Status`, `CostSavedINR`
    - Create `frontend/src/components/IncidentRow.tsx` rendering `ApproveButton` only when `Status === "PENDING_APPROVAL"`
    - Wire `ApproveButton` click to `POST /incidents/{incidentId}/approve`
    - _Requirements: 8.2, 8.3, 7.2, 7.3_

  - [ ]* 12.4 Write property test for `IncidentRow` approval button rendering (Property 14)
    - **Property 14: Dashboard approval button rendered for PENDING_APPROVAL**
    - **Validates: Requirements 7.2, 8.3**
    - Use `fast-check` with `fc.record({...})` generating incidents with varied `Status` values; use `@testing-library/react` to render `IncidentRow`; verify `ApproveButton` present iff `Status === "PENDING_APPROVAL"`

  - [~] 12.5 Implement `IncidentDetail`, `RcaPanel`, and `RemediationPanel` components
    - Create `frontend/src/components/IncidentDetail.tsx` fetching `GET /incidents/{incidentId}` and rendering full record
    - Create `frontend/src/components/RcaPanel.tsx` displaying `rootCause` and `confidence` (with visual confidence bar)
    - Create `frontend/src/components/RemediationPanel.tsx` displaying remediation plan and risk tier badge
    - _Requirements: 8.4_

  - [ ]* 12.6 Write property test for `RcaPanel` agent trace display (Property 15)
    - **Property 15: Dashboard agent trace display**
    - **Validates: Requirements 8.4**
    - Use `fast-check` with `fc.string()` for `rootCause` and `fc.float({min:0, max:1})` for `confidence`; render `RcaPanel`; verify both values appear in rendered output

  - [~] 12.7 Implement `CostSavingsSummary` component and `sumMonthlyCostINR` utility
    - Create `frontend/src/utils/costAggregation.ts` implementing `sumMonthlyCostINR(incidents)` filtering `RESOLVED` current-month incidents and summing `costSavedINR`
    - Create `frontend/src/components/CostSavingsSummary.tsx` displaying the aggregate INR value for the current calendar month
    - _Requirements: 8.5_

  - [ ]* 12.8 Write property test for `sumMonthlyCostINR` (Property 16)
    - **Property 16: Monthly cost aggregation correctness**
    - **Validates: Requirements 8.5**
    - Use `fast-check` with `fc.array(fc.record({status: fc.string(), timestamp: fc.date(), costSavedINR: fc.float({min:0})}))` to generate mixed incident lists; verify sum equals only `RESOLVED` current-month incidents

  - [~] 12.9 Implement `ErrorBanner` component and integrate error state
    - Create `frontend/src/components/ErrorBanner.tsx` rendering a dismissible banner with a human-readable error message
    - Integrate with `useIncidents` hook: render `ErrorBanner` whenever `error !== null`
    - _Requirements: 8.7_

  - [ ]* 12.10 Write property test for `ErrorBanner` on non-2xx API response (Property 17)
    - **Property 17: Dashboard error banner on non-2xx response**
    - **Validates: Requirements 8.7**
    - Use `fast-check` with `fc.integer({min:400, max:599})` for status codes; mock `axios` to reject with error; verify `useIncidents` sets non-null `error` and `ErrorBanner` is visible

  - [~] 12.11 Add Amplify hosting CDK construct or `amplify.yml`
    - Create `amplify.yml` with build commands (`npm run build`) and artifact path (`dist/`)
    - Add `aws_amplify.App` CDK construct connected to repository main branch for CI/CD
    - _Requirements: 8.1_

- [~] 13. Checkpoint — frontend and API complete
  - Ensure all frontend property tests and API handler tests pass, ask the user if questions arise.

- [ ] 14. Observability hardening
  - [~] 14.1 Add CloudWatch alarm for `IncidentResolutionTimeMs > 30 000 ms`
    - Create `aws_cloudwatch.Alarm` targeting `OmniTrace/IncidentResolutionTimeMs` metric, threshold 30000, comparison `GREATER_THAN_THRESHOLD`
    - Set alarm action to publish to `OmniTrace-Notifications` SNS topic
    - _Requirements: 11.3_

  - [~] 14.2 Add CloudWatch log groups and structured log validation
    - Define explicit `aws_logs.LogGroup` resources for each Lambda (retention 90 days)
    - Verify each Lambda emits JSON-structured logs via `emit_structured_log` (covered by Property 12 tests)
    - _Requirements: 1.3, 11.1_

  - [~] 14.3 Add Step Functions execution history retention setting
    - Set `logging_configuration` on the State Machine CDK construct to retain execution history in CloudWatch Logs for 90 days
    - _Requirements: 11.5_

- [ ] 15. Integration and smoke tests
  - [ ]* 15.1 Write integration test for EventBridge → Step Functions trigger
    - Deploy to a test environment; publish a valid OmniTrace event via `put_events`; verify Step Functions execution starts within 5 s
    - Mock agent Lambdas with stubs returning canned responses
    - _Requirements: 1.2_

  - [ ]* 15.2 Write integration test for full happy-path pipeline (LOW risk)
    - Invoke Simulator with `faultType=LatencySpike`, `severity=low`; wait for Step Functions execution to reach `RESOLVED`; verify DynamoDB record `Status=RESOLVED`, `CostSavedINR >= 0`, `AgentTraces` non-empty
    - _Requirements: 2.1, 2.3, 5.2, 6.2, 6.3_

  - [ ]* 15.3 Write integration test for MEDIUM risk approval flow
    - Trigger incident yielding MEDIUM risk; verify DynamoDB `Status=PENDING_APPROVAL`; call `POST /approve`; verify Step Functions resumes and reaches `RESOLVED`
    - _Requirements: 7.2, 7.3, 9.3_

  - [ ]* 15.4 Write smoke tests for infrastructure configuration
    - Verify DynamoDB table has PITR enabled and TTL attribute `ExpiresAt` configured
    - Verify all five IAM roles exist and have no admin wildcards
    - Verify Amplify app is connected to the repository main branch
    - _Requirements: 6.4, 6.5, 12.1–12.4, 8.1_

- [~] 16. Final checkpoint — full system validation
  - Ensure all unit, property, integration, and smoke tests pass. Confirm CloudWatch alarm is active. Ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- Property tests use `hypothesis` (Python) and `fast-check` (TypeScript/React)
- All Python Lambdas target runtime Python 3.12; frontend uses React 18 + Tailwind CSS 3 + Vite 5
- Mock `boto3` clients with `moto` or `unittest.mock` to keep tests fast and cost-free
- CDK constructs centralise all IaC; no manual console configuration required
- All cost-savings values are denominated in INR (Indian Rupees)
- Checkpoints validate incremental progress before proceeding to the next phase

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.5"] },
    { "id": 2, "tasks": ["1.4", "1.6", "2.1", "2.3", "2.6"] },
    { "id": 3, "tasks": ["2.2", "2.4", "2.5", "2.7", "4.1", "5.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "5.2", "6.1", "7.1", "8.1"] },
    { "id": 5, "tasks": ["5.3", "6.2", "6.3", "6.4", "7.2", "7.3", "8.2", "8.3", "8.4"] },
    { "id": 6, "tasks": ["8.5", "8.6", "10.1", "10.2", "10.4", "11.1", "11.2", "12.1"] },
    { "id": 7, "tasks": ["10.3", "10.5", "10.6", "11.3", "11.4", "12.2"] },
    { "id": 8, "tasks": ["12.3", "12.5", "12.7", "12.9", "12.11", "14.1", "14.2", "14.3"] },
    { "id": 9, "tasks": ["12.4", "12.6", "12.8", "12.10"] },
    { "id": 10, "tasks": ["15.1", "15.2", "15.3", "15.4"] }
  ]
}
```
