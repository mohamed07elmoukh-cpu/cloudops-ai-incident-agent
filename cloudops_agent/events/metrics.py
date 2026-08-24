"""Prometheus metrics emitted by the incident worker."""

from prometheus_client import CollectorRegistry, Counter, Histogram

WORKER_REGISTRY = CollectorRegistry()

EVENTS_RECEIVED = Counter(
    "cloudops_events_received_total",
    "Normalized events received from SQS.",
    registry=WORKER_REGISTRY,
)
EVENTS_PROCESSED = Counter(
    "cloudops_events_processed_total",
    "Events committed successfully.",
    registry=WORKER_REGISTRY,
)
EVENTS_FAILED = Counter(
    "cloudops_events_failed_total",
    "Events that failed validation or processing.",
    registry=WORKER_REGISTRY,
)
EVENTS_DUPLICATE = Counter(
    "cloudops_events_duplicate_total",
    "Already processed events ignored by the worker.",
    registry=WORKER_REGISTRY,
)
EVENT_PROCESSING_SECONDS = Histogram(
    "cloudops_event_processing_seconds",
    "Time spent validating and committing one event.",
    registry=WORKER_REGISTRY,
)
INCIDENTS_CREATED = Counter(
    "cloudops_incidents_created_total",
    "Incidents created by normalized events.",
    registry=WORKER_REGISTRY,
)

