"""AWS service adapters."""

from cloudops_agent.adapters.aws.correlation import CloudWatchAlarmTagResolver
from cloudops_agent.adapters.aws.metrics import CloudWatchMetricsError, CloudWatchMetricsReader
from cloudops_agent.adapters.aws.pricing import (
    AwsPricingError,
    AwsPricingEstimator,
    DemoPricingEstimator,
)
from cloudops_agent.adapters.aws.remediation import AwsActionError, AwsRemediationAdapter

__all__ = [
    "AwsActionError",
    "AwsPricingError",
    "AwsPricingEstimator",
    "DemoPricingEstimator",
    "AwsRemediationAdapter",
    "CloudWatchAlarmTagResolver",
    "CloudWatchMetricsError",
    "CloudWatchMetricsReader",
]
