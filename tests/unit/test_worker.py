from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from cloudops_agent.events.consumer import IncidentWorker
from cloudops_agent.events.models import CloudEventEnvelope
from cloudops_agent.events.queue import InMemoryEventQueue
from cloudops_agent.models import Incident, ProcessedEvent


def event(source: str = "demo-service") -> CloudEventEnvelope:
    return CloudEventEnvelope.model_validate_json(
        json.dumps(
            {
                "event_id": str(uuid.uuid4()),
                "event_type": "METRIC_THRESHOLD_BREACHED",
                "source": source,
                "occurred_at": datetime.now(UTC).isoformat(),
                "severity": "HIGH",
                "correlation_key": f"{source}:cpu-saturation",
                "payload": {
                    "metric_name": "demo_cpu_load_percent",
                    "value": 92,
                    "threshold": 85,
                    "alert_status": "firing",
                    "labels": {"service": source},
                    "annotations": {},
                },
                "schema_version": "1.0",
                "trace_id": str(uuid.uuid4()),
            }
        )
    )


def factory(engine: Engine) -> Callable[[], Session]:
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return sessions


def test_worker_processes_event_and_deletes_message_after_commit(engine: Engine) -> None:
    queue = InMemoryEventQueue()
    queue.publish(event())
    worker = IncidentWorker(queue, factory(engine))

    assert worker.run_once(wait_time_seconds=0) == 1

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Incident)) == 1
        assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1
    assert len(queue.deleted_receipts) == 1
    assert queue.approximate_counts() == (0, 0)


def test_duplicate_event_is_ignored_and_both_messages_are_deleted(engine: Engine) -> None:
    queue = InMemoryEventQueue()
    duplicate = event()
    queue.publish(duplicate)
    queue.publish(duplicate)
    worker = IncidentWorker(queue, factory(engine))

    assert worker.run_once(wait_time_seconds=0) == 2

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Incident)) == 1
        assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1
    assert len(queue.deleted_receipts) == 2


def test_invalid_message_is_not_deleted(engine: Engine) -> None:
    queue = InMemoryEventQueue()
    queue.publish_raw('{"invalid": true}')
    worker = IncidentWorker(queue, factory(engine))

    assert worker.run_once(wait_time_seconds=0) == 1

    assert queue.deleted_receipts == []
    assert queue.approximate_counts() == (1, 0)


def test_processing_failure_does_not_delete_message(engine: Engine) -> None:
    queue = InMemoryEventQueue()
    invalid_payload = event().model_copy(
        update={"payload": {"metric_name": "demo_cpu_load_percent"}}
    )
    queue.publish(invalid_payload)
    worker = IncidentWorker(queue, factory(engine))

    assert worker.run_once(wait_time_seconds=0) == 1

    assert queue.deleted_receipts == []
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 0

