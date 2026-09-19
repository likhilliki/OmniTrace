"""
Observability telemetry helpers for OmniTrace.

Provides:
  - emit_structured_log   — writes a JSON-structured log entry to stdout
                            (captured by CloudWatch Logs)
  - publish_resolution_metrics — publishes IncidentResolutionTimeMs and
                                 RemediationCostSavedINR to CloudWatch Metrics
"""

import json
import os
from datetime import datetime, timezone

import boto3

# ---------------------------------------------------------------------------
# CloudWatch client (module-level so it can be easily swapped in tests)
# ---------------------------------------------------------------------------
_cw_client = None


def _get_cw_client():
    """Lazy-initialise the CloudWatch boto3 client."""
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch")
    return _cw_client


def _set_cw_client(client) -> None:
    """Override the CloudWatch client (used in tests)."""
    global _cw_client
    _cw_client = client


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def emit_structured_log(
    agent_name: str,
    incident_id: str,
    duration_ms: float,
    status: str,
    error_details: "str | None",
) -> None:
    """Write a JSON-structured log entry to stdout (captured by CloudWatch Logs).

    Args:
        agent_name:    Name of the emitting agent (e.g. "Auditor").
        incident_id:   The incident identifier (e.g. "INC-20240901-abc123").
        duration_ms:   Elapsed time in milliseconds (will be rounded to int).
        status:        Execution status string (e.g. "SUCCESS" or "FAILED").
        error_details: Human-readable error description, or None when healthy.

    The output dict contains exactly five fields:
        incidentId, agentName, durationMs (int ≥ 0), status, errorDetails.
    """
    entry = {
        "incidentId": incident_id,
        "agentName": agent_name,
        "durationMs": round(duration_ms),
        "status": status,
        "errorDetails": error_details,
    }
    print(json.dumps(entry))


def publish_resolution_metrics(
    incident_id: str,
    resolution_time_ms: float,
    cost_saved_inr: float,
) -> None:
    """Publish resolution metrics to Amazon CloudWatch.

    Publishes two metrics in a single ``put_metric_data`` call:
      - ``IncidentResolutionTimeMs`` (unit: Milliseconds)
      - ``RemediationCostSavedINR``  (unit: None)

    Both metrics carry a single dimension ``IncidentID = incident_id`` and
    are timestamped with the current UTC time.

    The CloudWatch namespace is read from the ``CW_NAMESPACE`` environment
    variable; it defaults to ``"OmniTrace"`` when the variable is absent.

    Args:
        incident_id:        The incident identifier.
        resolution_time_ms: Elapsed milliseconds from EventBridge ingestion to
                            RESOLVED status.
        cost_saved_inr:     Cost savings for this incident in Indian Rupees.
    """
    namespace = os.environ.get("CW_NAMESPACE", "OmniTrace")
    timestamp = datetime.now(timezone.utc)

    dimensions = [{"Name": "IncidentID", "Value": incident_id}]

    _get_cw_client().put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": "IncidentResolutionTimeMs",
                "Value": resolution_time_ms,
                "Unit": "Milliseconds",
                "Dimensions": dimensions,
                "Timestamp": timestamp,
            },
            {
                "MetricName": "RemediationCostSavedINR",
                "Value": cost_saved_inr,
                "Unit": "None",
                "Dimensions": dimensions,
                "Timestamp": timestamp,
            },
        ],
    )
