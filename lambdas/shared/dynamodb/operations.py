"""
DynamoDB operations module for OmniTrace.

Provides functions for creating and updating incident records in the
OmniTraceIncidents single-table. All writes use boto3.resource('dynamodb').

Table schema:
  PK: IncidentID (String)
  SK: Timestamp  (String, ISO-8601 UTC)

Requirements: 6.1, 6.2, 6.3, 6.5
"""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

# ---------------------------------------------------------------------------
# Table reference
# ---------------------------------------------------------------------------

_DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "OmniTraceIncidents")

_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(_DYNAMODB_TABLE_NAME)


# ---------------------------------------------------------------------------
# TTL helper
# ---------------------------------------------------------------------------

def compute_ttl(iso_timestamp: str, days: int) -> int:
    """Return the Unix epoch integer for iso_timestamp + *days* days.

    Args:
        iso_timestamp: An ISO-8601 UTC string, e.g. "2024-09-01T14:23:05Z"
                       or "2024-09-01T14:23:05+00:00".
        days:          Number of days to add.

    Returns:
        Unix epoch as a plain Python int.

    Requirement: 6.5 — ExpiresAt set to 90 days from incident creation.
    """
    # Normalise the Z suffix so fromisoformat handles it on Python 3.10 and below.
    normalised = iso_timestamp.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalised)
    return int((dt + timedelta(days=days)).timestamp())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_incident_record(incident_id: str, timestamp: str, fault_type: str) -> None:
    """Write the initial OPEN record for a new incident.

    Sets:
      - IncidentID: incident_id
      - Timestamp:  timestamp  (ISO-8601 sort key)
      - Status:     "OPEN"
      - AgentTraces: []
      - CostSavedINR: Decimal("0")
      - FaultType:  fault_type
      - ExpiresAt:  compute_ttl(timestamp, 90)  (Unix epoch, used as DynamoDB TTL)

    Args:
        incident_id: Unique incident identifier (e.g. "INC-20240901-abc123").
        timestamp:   ISO-8601 UTC creation time.
        fault_type:  One of LatencySpike | HTTP5xxError | MemoryOOM.

    Requirements: 6.1, 6.2, 6.5
    """
    expires_at = compute_ttl(timestamp, 90)
    item = {
        "IncidentID": incident_id,
        "Timestamp": timestamp,
        "Status": "OPEN",
        "AgentTraces": [],
        "CostSavedINR": Decimal("0"),
        "FaultType": fault_type,
        "ExpiresAt": expires_at,
    }

    _table.put_item(Item=item)

    _log(
        operation="create_incident_record",
        incident_id=incident_id,
        timestamp=timestamp,
        fault_type=fault_type,
        expires_at=expires_at,
    )


def update_incident_status(incident_id: str, timestamp: str, status: str) -> None:
    """Update only the Status attribute of an existing incident record.

    Args:
        incident_id: Partition key of the incident to update.
        timestamp:   Sort key of the incident to update.
        status:      New status string, e.g. "RESOLVED", "FAILED", "PENDING_APPROVAL".

    Requirement: 6.3
    """
    _table.update_item(
        Key={"IncidentID": incident_id, "Timestamp": timestamp},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":s": status},
    )

    _log(
        operation="update_incident_status",
        incident_id=incident_id,
        timestamp=timestamp,
        new_status=status,
    )


def append_agent_trace(incident_id: str, timestamp: str, trace: dict) -> None:
    """Append a trace entry to the AgentTraces list of an existing incident.

    Uses DynamoDB's ``list_append`` to atomically extend the list without
    overwriting existing entries.

    Args:
        incident_id: Partition key of the incident.
        timestamp:   Sort key of the incident.
        trace:       A dict conforming to the AgentTrace schema, e.g.
                     {executionArn, executionName, agentName, durationMs, status}.

    Requirement: 6.2 (AgentTraces maintained per incident)
    """
    _table.update_item(
        Key={"IncidentID": incident_id, "Timestamp": timestamp},
        UpdateExpression="SET AgentTraces = list_append(AgentTraces, :t)",
        ExpressionAttributeValues={":t": [trace]},
    )

    _log(
        operation="append_agent_trace",
        incident_id=incident_id,
        timestamp=timestamp,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(**fields) -> None:
    """Print a JSON-structured log line to stdout for CloudWatch capture."""
    print(json.dumps(fields, default=str))
