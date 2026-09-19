"""
EventBridge event schema validator for OmniTrace.

Validates that incoming EventBridge events conform to the required schema
before the orchestration pipeline is triggered.

Requirements: 1.1, 1.3
"""

from __future__ import annotations

# Supported fault event types (Requirement 1.4)
REQUIRED_FAULT_TYPES: set[str] = {"LatencySpike", "HTTP5xxError", "MemoryOOM"}


def _is_non_empty_string(value: object) -> bool:
    """Return True iff value is a str with at least one character."""
    return isinstance(value, str) and len(value) > 0


def validate_event(event: dict) -> bool:
    """
    Validate that an EventBridge event conforms to the OmniTrace schema.

    Returns True iff ALL five required fields are present and non-empty:
        - source               (top-level)
        - detail-type          (top-level)
        - detail.incidentId    (nested under "detail")
        - detail.faultType     (nested under "detail")
        - detail.timestamp     (nested under "detail")

    Returns False (never raises) for any missing, non-string, or empty field,
    allowing callers to decide how to handle invalid events (e.g. route to DLQ).

    Args:
        event: The raw EventBridge event dict.

    Returns:
        bool: True if the event passes schema validation, False otherwise.
    """
    if not isinstance(event, dict):
        return False

    # Validate top-level fields
    if not _is_non_empty_string(event.get("source")):
        return False

    if not _is_non_empty_string(event.get("detail-type")):
        return False

    # Validate nested detail fields
    detail = event.get("detail")
    if not isinstance(detail, dict):
        return False

    if not _is_non_empty_string(detail.get("incidentId")):
        return False

    if not _is_non_empty_string(detail.get("faultType")):
        return False

    if not _is_non_empty_string(detail.get("timestamp")):
        return False

    return True


def validate_fault_type(fault_type: str) -> bool:
    """
    Check whether a fault type is one of the supported OmniTrace fault types.

    Args:
        fault_type: The fault type string to validate.

    Returns:
        bool: True if fault_type is in REQUIRED_FAULT_TYPES, False otherwise.
    """
    return fault_type in REQUIRED_FAULT_TYPES
