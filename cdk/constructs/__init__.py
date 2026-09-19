"""
OmniTrace CDK constructs package.

Each module in this package defines a reusable CDK Construct that
encapsulates a logical grouping of AWS resources.
"""

from cdk.constructs.iam_roles import OmniTraceIamRoles

__all__ = ["OmniTraceIamRoles"]
