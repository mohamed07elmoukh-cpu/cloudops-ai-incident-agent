"""FastAPI entrypoint for the local CloudOps incident scenario."""

from __future__ import annotations

import json
import os
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from cloudops_agent.adapters.aws import AwsRemediationAdapter
from cloudops_agent.database import get_session
from cloudops_agent.detection import DetectionService
from cloudops_agent.events.alertmanager import (
    AlertmanagerWebhook,
    alertmanager_to_cloud_events,
)
from cloudops_agent.events.queue import EventQueue, SqsEventQueue
from cloudops_agent.models import (
    Incident,
    IncidentStatus,
    ProcessedEvent,
    PublishedEvent,
    RemediationExecution,
    Severity,
)
from cloudops_agent.remediation.executor import (
    ApprovalRequiredError,
    AwsRemediationExecutor,
    DuplicateRemediationError,
    InvalidIncidentStateError,
    RemediationCooldownError,
    RemediationError,
    RollbackError,
    RunbookNotAllowedError,
    SimulatedRemediationExecutor,
)
from cloudops_agent.remediation.runbooks import InvalidRunbookError, RunbookLoader
from cloudops_agent.schemas import (
    DailyIncidentPoint,
    DetectionEvaluationResponse,
    IncidentRead,
    IncidentStatistics,
    MetricEvaluationRequest,
    ProcessedEventRead,
    RemediationRequest,
    ResourceMetricEvaluationRequest,
    RollbackRequest,
    SystemComponentHealth,
    SystemHealthRead,
    TimelineEntry,
    VerificationRequest,
)
from cloudops_agent.verification.service import VerificationError, VerificationService

RUNBOOK_DIRECTORY = Path(
    os.getenv("RUNBOOK_DIRECTORY", Path(__file__).resolve().parents[2] / "runbooks")
)

app = FastAPI(
    title="CloudOps AI Incident Agent",
    version="0.1.0",
    description="Incident detection and policy-guarded AWS capacity remediation.",
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
def list_incidents(
    response: Response,
    session: SessionDependency,
    incident_status: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    source: str | None = None,
    incident_type: str | None = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Literal["newest", "oldest"] = "newest",
) -> list[Incident]:
    filters = []
    if incident_status is not None:
        filters.append(Incident.status == incident_status)
    if severity is not None:
        filters.append(Incident.severity == severity)
    if source:
        filters.append(Incident.source == source)
    if incident_type:
        filters.append(Incident.incident_type == incident_type)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                Incident.title.ilike(pattern),
                Incident.description.ilike(pattern),
                Incident.source.ilike(pattern),
                Incident.correlation_key.ilike(pattern),
            )
        )

    total_query = select(func.count()).select_from(Incident).where(*filters)
    total = int(session.scalar(total_query) or 0)
    ordering = Incident.detected_at.desc() if sort == "newest" else Incident.detected_at.asc()
    query = (
        _incident_query()
        .where(*filters)
        .order_by(ordering)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)
    return list(session.scalars(query).unique())


@app.get("/api/incidents/{incident_id}", response_model=IncidentRead)
def get_incident(incident_id: uuid.UUID, session: SessionDependency) -> Incident:
    return _get_incident_or_404(session, incident_id)


@app.get("/api/incidents/{incident_id}/events", response_model=list[ProcessedEventRead])
def get_incident_events(
    incident_id: uuid.UUID, session: SessionDependency
) -> list[ProcessedEventRead]:
    _get_incident_or_404(session, incident_id)
    rows = session.execute(
        select(ProcessedEvent, PublishedEvent)
        .outerjoin(PublishedEvent, PublishedEvent.event_id == ProcessedEvent.event_id)
        .where(ProcessedEvent.incident_id == incident_id)
        .order_by(ProcessedEvent.processed_at.desc())
    ).all()
    return [
        ProcessedEventRead(
            event_id=event.event_id,
            event_type=event.event_type,
            processed_at=event.processed_at,
            incident_id=event.incident_id,
            status=event.status,
            trace_id=event.trace_id,
            published_at=publication.published_at if publication else None,
            message_id=publication.message_id if publication else None,
        )
        for event, publication in rows
    ]


@app.get("/api/incidents/{incident_id}/timeline", response_model=list[TimelineEntry])
def get_incident_timeline(
    incident_id: uuid.UUID, session: SessionDependency
) -> list[TimelineEntry]:
    incident = _get_incident_or_404(session, incident_id)
    entries = [
        TimelineEntry(
            timestamp=incident.detected_at,
            kind="incident",
            title="Incident détecté",
            status=IncidentStatus.OPEN,
            detail={"severity": incident.severity, "source": incident.source},
        )
    ]
    for evidence in incident.evidence:
        entries.append(
            TimelineEntry(
                timestamp=evidence.timestamp,
                kind="evidence",
                title=f"Evidence {evidence.metric_name}",
                detail={"value": evidence.metric_value, "threshold": evidence.threshold},
            )
        )
    events = session.scalars(
        select(ProcessedEvent).where(ProcessedEvent.incident_id == incident_id)
    )
    for event in events:
        entries.append(
            TimelineEntry(
                timestamp=event.processed_at,
                kind="event",
                title=event.event_type,
                status=event.status,
                detail={"event_id": str(event.event_id), "trace_id": str(event.trace_id)},
            )
        )
    for execution in incident.remediation_executions:
        entries.append(
            TimelineEntry(
                timestamp=execution.started_at,
                kind="remediation",
                title=f"Runbook {execution.runbook_name}",
                status=execution.status,
                detail={"idempotency_key": execution.idempotency_key},
            )
        )
        if execution.completed_at:
            entries.append(
                TimelineEntry(
                    timestamp=execution.completed_at,
                    kind="remediation",
                    title="Remédiation terminée",
                    status=execution.status,
                )
            )
    if incident.resolved_at:
        entries.append(
            TimelineEntry(
                timestamp=incident.resolved_at,
                kind="incident",
                title="Incident résolu",
                status=IncidentStatus.RESOLVED,
            )
        )
    return sorted(entries, key=lambda item: item.timestamp, reverse=True)


@app.get("/api/statistics", response_model=IncidentStatistics)
def get_statistics(session: SessionDependency) -> IncidentStatistics:
    incidents = list(session.scalars(select(Incident).order_by(Incident.detected_at)))
    by_status = Counter(incident.status.value for incident in incidents)
    by_severity = Counter(incident.severity.value for incident in incidents)
    resolution_times = [
        (incident.resolved_at - incident.detected_at).total_seconds()
        for incident in incidents
        if incident.resolved_at is not None
    ]
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=13)
    points: list[DailyIncidentPoint] = []
    for offset in range(14):
        day = start_date + timedelta(days=offset)
        points.append(
            DailyIncidentPoint(
                date=day.isoformat(),
                detected=sum(incident.detected_at.date() == day for incident in incidents),
                resolved=sum(
                    incident.resolved_at is not None and incident.resolved_at.date() == day
                    for incident in incidents
                ),
            )
        )
    terminal = {IncidentStatus.RESOLVED.value, IncidentStatus.FAILED.value}
    return IncidentStatistics(
        total=len(incidents),
        open=by_status[IncidentStatus.OPEN.value],
        resolved=by_status[IncidentStatus.RESOLVED.value],
        escalated=by_status[IncidentStatus.ESCALATED.value],
        active=sum(count for key, count in by_status.items() if key not in terminal),
        average_resolution_seconds=(
            round(sum(resolution_times) / len(resolution_times), 2) if resolution_times else None
        ),
        by_status=dict(by_status),
        by_severity=dict(by_severity),
        daily_trend=points,
    )


def _worker_health() -> tuple[bool, str | None]:
    url = os.getenv("WORKER_HEALTH_URL", "http://localhost:8002/health")
    try:
        with urllib.request.urlopen(url, timeout=2) as worker_response:
            payload = json.loads(worker_response.read())
        healthy = worker_response.status == 200 and payload.get("status") == "ok"
        return healthy, None if healthy else "worker reported an unhealthy state"
    except Exception as exc:
        return False, str(exc)


@app.get("/api/system/health", response_model=SystemHealthRead)
def get_system_health(
    response: Response, session: SessionDependency, queue: QueueDependency
) -> SystemHealthRead:
    components: dict[str, SystemComponentHealth] = {
        "api": SystemComponentHealth(status="healthy")
    }
    try:
        session.execute(text("SELECT 1"))
        components["postgresql"] = SystemComponentHealth(status="healthy")
    except Exception as exc:
        components["postgresql"] = SystemComponentHealth(status="unhealthy", detail=str(exc))
    try:
        queue_ok = queue.health()
        visible, in_flight = queue.approximate_counts() if queue_ok else (None, None)
        components["sqs"] = SystemComponentHealth(
            status="healthy" if queue_ok else "unhealthy",
            visible_messages=visible,
            in_flight_messages=in_flight,
        )
    except Exception as exc:
        components["sqs"] = SystemComponentHealth(status="unhealthy", detail=str(exc))
    worker_ok, worker_detail = _worker_health()
    components["worker"] = SystemComponentHealth(
        status="healthy" if worker_ok else "unhealthy", detail=worker_detail
    )
    all_healthy = all(item.status == "healthy" for item in components.values())
    overall = "healthy" if all_healthy else "degraded"
    if overall != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return SystemHealthRead(
        status=overall,
        checked_at=datetime.now(UTC),
        components=components,
    )


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


@app.post("/api/detection/resources/evaluate", response_model=DetectionEvaluationResponse)
def evaluate_resource_detection(
    metric: ResourceMetricEvaluationRequest, session: SessionDependency
) -> DetectionEvaluationResponse:
    result = DetectionService(session).evaluate_resource(metric)
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
        executor: SimulatedRemediationExecutor
        if runbook.executor == "aws" and os.getenv("REMEDIATION_MODE", "simulated") == "aws":
            executor = AwsRemediationExecutor(session, AwsRemediationAdapter())
        else:
            executor = SimulatedRemediationExecutor(session)
        executor.execute(
            incident,
            runbook,
            parameters=request.parameters,
            idempotency_key=request.idempotency_key,
            approved_by=request.approved_by,
            estimated_monthly_cost_delta_usd=request.estimated_monthly_cost_delta_usd,
        )
    except (
        DuplicateRemediationError,
        InvalidIncidentStateError,
        RemediationCooldownError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (InvalidRunbookError, RunbookNotAllowedError, RemediationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _get_incident_or_404(session, incident_id)


@app.post("/api/incidents/{incident_id}/rollback", response_model=IncidentRead)
def rollback_incident_remediation(
    incident_id: uuid.UUID,
    request: RollbackRequest,
    session: SessionDependency,
) -> Incident:
    incident = _get_incident_or_404(session, incident_id)
    execution = session.get(RemediationExecution, request.execution_id)
    if execution is None or execution.incident_id != incident.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="remediation execution not found for incident",
        )
    try:
        runbook = RunbookLoader(RUNBOOK_DIRECTORY).load(execution.runbook_name)
        executor: SimulatedRemediationExecutor
        if runbook.executor == "aws" and os.getenv("REMEDIATION_MODE", "simulated") == "aws":
            executor = AwsRemediationExecutor(session, AwsRemediationAdapter())
        else:
            executor = SimulatedRemediationExecutor(session)
        executor.rollback(
            incident,
            execution,
            runbook,
            approved_by=request.approved_by,
        )
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (InvalidRunbookError, RollbackError, RemediationError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _get_incident_or_404(session, incident_id)


@app.post("/api/incidents/{incident_id}/verify", response_model=IncidentRead)
def verify_incident(
    incident_id: uuid.UUID,
    request: VerificationRequest,
    session: SessionDependency,
) -> Incident:
    incident = _get_incident_or_404(session, incident_id)
    try:
        VerificationService(session).verify(
            incident,
            request.metric_name,
            request.value,
            request.timestamp,
        )
    except VerificationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _get_incident_or_404(session, incident_id)
