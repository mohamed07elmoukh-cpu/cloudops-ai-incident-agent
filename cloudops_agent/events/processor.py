"""Transactional adapter from normalized events to the detection domain."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from cloudops_agent.detection import DetectionService
from cloudops_agent.events.models import CloudEventEnvelope, MetricThresholdPayload
from cloudops_agent.models import ProcessedEvent
from cloudops_agent.schemas import MetricEvaluationRequest


@dataclass(frozen=True)
class ProcessingResult:
    duplicate: bool
    incident_created: bool
    incident_id: str | None
    status: str


class IncidentEventProcessor:
    """Process one event and commit its idempotence record atomically."""

    def process(self, event: CloudEventEnvelope, session: Session) -> ProcessingResult:
        existing = session.get(ProcessedEvent, event.event_id)
        if existing is not None:
            return ProcessingResult(
                duplicate=True,
                incident_created=False,
                incident_id=str(existing.incident_id) if existing.incident_id else None,
                status=existing.status,
            )

        if event.event_type != "METRIC_THRESHOLD_BREACHED":
            processed = ProcessedEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                incident_id=None,
                status="IGNORED",
                trace_id=event.trace_id,
            )
            session.add(processed)
            session.commit()
            return ProcessingResult(False, False, None, "IGNORED")

        payload = MetricThresholdPayload.model_validate(event.payload)
        if payload.alert_status != "firing":
            raise ValueError("threshold breach event must have alert_status=firing")
        metric = MetricEvaluationRequest(
            source=event.source,
            metric_name="cpu_usage_percent",
            value=payload.value,
            threshold=payload.threshold,
            timestamp=event.occurred_at,
        )
        try:
            detection = DetectionService(session).evaluate(
                metric,
                correlation_key=event.correlation_key,
                raw_data={
                    "cloud_event": event.model_dump(mode="json"),
                    "original_metric_name": payload.metric_name,
                },
                commit=False,
            )
            incident_id = detection.incident.id if detection.incident else None
            session.add(
                ProcessedEvent(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    incident_id=incident_id,
                    status="PROCESSED",
                    trace_id=event.trace_id,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        return ProcessingResult(
            duplicate=False,
            incident_created=detection.incident_created,
            incident_id=str(incident_id) if incident_id else None,
            status="PROCESSED",
        )

