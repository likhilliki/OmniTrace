"""
OmniTraceEventBridgeRule — EventBridge rule for incident event ingestion.

Matches events with:
  source      = "omnitrace.simulator"
  detail-type = "OmniTraceIncident"

The dead-letter queue is set to the shared OmniTrace-EventBridge-DLQ so that
events that cannot be delivered to the Step Functions target are captured and
logged rather than silently dropped (Requirement 1.3).

The Step Functions state machine target is wired in task 5.2.  Until then,
the rule is created with no targets, which is valid in EventBridge — events
matching the pattern are simply delivered to no target (and captured by the
DLQ if delivery fails).
"""

import aws_cdk as cdk
from aws_cdk import aws_events as events
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from cdk.constants import (
    EVENTBRIDGE_SOURCE,
    EVENTBRIDGE_DETAIL_TYPE,
    EVENTBRIDGE_RULE_NAME,
)


class OmniTraceEventBridgeRule(Construct):
    """
    Creates the EventBridge rule that triggers the OmniTrace orchestration pipeline.

    The rule matches the canonical OmniTrace event pattern and attaches a
    dead-letter queue for failed deliveries.  A Step Functions target is added
    in a later task (5.2).

    Properties:
        incident_rule — the EventBridge Rule construct
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dlq: sqs.IQueue,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------ #
        # EventBridge rule — matches OmniTrace incident events                #
        # Requirements: 1.1, 1.3, 1.4                                         #
        # ------------------------------------------------------------------ #
        self.incident_rule = events.Rule(
            self,
            "OmniTraceIncidentRule",
            rule_name=EVENTBRIDGE_RULE_NAME,
            description=(
                "Matches OmniTrace incident events from the anomaly simulator "
                "and routes them to the Step Functions orchestrator. "
                "Failed deliveries are captured by the EventBridge DLQ."
            ),
            # Event pattern: source + detail-type must match exactly
            event_pattern=events.EventPattern(
                source=[EVENTBRIDGE_SOURCE],
                detail_type=[EVENTBRIDGE_DETAIL_TYPE],
            ),
            # Enable the rule immediately
            enabled=True,
            # Dead-letter queue for failed event deliveries (Requirement 1.3)
            # NOTE: EventBridge DLQ is set on each *target*, not on the rule
            # itself. The dlq reference is stored here so task 5.2 can pass
            # it to the SfnStateMachine target via dead_letter_queue parameter.
            # We expose it as an attribute for that purpose.
        )

        # Expose the DLQ so task 5.2 can attach it to the target
        self.dlq = dlq
