"""FastAPI entrypoint for the local CloudOps incident scenario."""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session, selectinload

from cloudops_agent.database import get_session
from cloudops_agent.detection import DetectionService
from cloudops_agent.events.alertmanager import (
    AlertmanagerWebhook,
    alertmanager_to_cloud_events,
)
from cloudops_agent.events.queue import EventQueue, SqsEventQueue
from cloudops_agent.models import Incident, PublishedEvent
from cloudops_agent.remediation.executor import (
    DuplicateRemediationError,
    InvalidIncidentStateError,
    RemediationError,
    RunbookNotAllowedError,
    SimulatedRemediationExecutor,
)
from cloudops_agent.remediation.runbooks import InvalidRunbookError, RunbookLoader
from cloudops_agent.schemas import (
    DetectionEvaluationResponse,
    IncidentRead,
    MetricEvaluationRequest,
    RemediationRequest,
    VerificationRequest,
)
from cloudops_agent.verification.service import VerificationError, VerificationService

RUNBOOK_DIRECTORY = Path(
    os.getenv("RUNBOOK_DIRECTORY", Path(__file__).resolve().parents[2] / "runbooks")
)

app = FastAPI(
    title="CloudOps AI Incident Agent",
    version="0.1.0",
    description="Local incident detection and policy-guarded simulated remediation.",
)
SessionDependency = Annotated[Session, Depends(get_session)]


@lru_cache
def get_event_queue() -> EventQueue:
    return SqsEventQueue.from_environment()


QueueDependency = Annotated[EventQueue, Depends(get_event_queue)]


def _incident_query() -> Select[tuple[Incident]]:
    return select(Incident).options(
        selectinload(Incident.evidence),
        selectinload(Incident.remediation_executions),
    )


def _get_incident_or_404(session: Session, incident_id: uuid.UUID) -> Incident:
    incident = session.scalar(_incident_query().where(Incident.id == incident_id))
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return incident


@app.get("/health")
def health(session: SessionDependency) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
        ) from exc
    return {"status": "ok"}


@app.get("/api/incidents", response_model=list[IncidentRead])
def list_incidents(session: SessionDependency) -> list[Incident]:
    query = _incident_query().order_by(Incident.detected_at.desc())
    return list(session.scalars(query).unique())


@app.get("/api/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: uuid.UUID, session: SessionDependency) -> Incident:
    return _get_incident_or_404(session, incident_id)


@app.post("/api/detection/evaluate", response_model=DetectionEvaluationResponse)
def evaluate_detection(
    metric: MetricEvaluationRequest, session: SessionDependency
) -> DetectionEvaluationResponse:
    result = DetectionService(session).evaluate(metric)
    incident = IncidentRead.model_validate(result.incident) if result.incident else None
    return DetectionEvaluationResponse(
        anomaly_detected=result.anomaly_detected,
        incident_created=result.incident_created,
        incident=incident,
    )


@app.post("/api/webhooks/alertmanager", status_code=status.HTTP_202_ACCEPTED)
def receive_alertmanager_webhook(
    webhook: AlertmanagerWebhook,
    session: SessionDependency,
    queue: QueueDependency,
) -> dict[str, object]:
    try:
        events = alertmanager_to_cloud_events(webhook)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    published = 0
    duplicate = 0
    event_ids: list[str] = []
    seen_in_request: set[uuid.UUID] = set()
    try:
        for event in events:
            event_ids.append(str(event.event_id))
            existing_publication = session.get(PublishedEvent, event.event_id)
            if event.event_id in seen_in_request or existing_publication is not None:
                duplicate += 1
                continue
            message_id = queue.publish(event)
            session.add(
                PublishedEvent(
                    event_id=event.event_id,
                    trace_id=event.trace_id,
                    message_id=message_id,
                )
            )
            seen_in_request.add(event.event_id)
            published += 1
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="event queue publication failed",
        ) from exc
    return {
        "accepted": len(events),
        "published": published,
        "duplicates": duplicate,
        "event_ids": event_ids,
    }


@app.post("/api/incidents/{incident_id}/remediate", response_model=IncidentRead)
def remediate_incident(
    incident_id: uuid.UUID,
    request: RemediationRequest,
    session: SessionDependency,
) -> Incident:
    incident = _get_incident_or_404(session, incident_id)
    loader = RunbookLoader(RUNBOOK_DIRECTORY)
    try:
        runbook = (
            loader.load(request.runbook_name)
            if request.runbook_name
            else loader.find_for_incident(incident.incident_type)
        )
        SimulatedRemediationExecutor(session).execute(
            incident,
            runbook,
            parameters=request.parameters,
            idempotency_key=request.idempotency_key,
        )
    except (DuplicateRemediationError, InvalidIncidentStateError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (InvalidRunbookError, RunbookNotAllowedError, RemediationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _get_incident_or_404(session, incident_id)


@app.post("/api/incidents/{incident_id}/verify", response_model=IncidentRead)
def verify_incident(
    incident_id: uuid.UUID,
    request: VerificationRequest,
    session: SessionDependency,
) -> Incident:
    incident = _get_incident_or_404(session, incident_id)
    try:
        VerificationService(session).verify_cpu(incident, request.value, request.timestamp)
    except VerificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _get_incident_or_404(session, incident_id)
