from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cloudops_agent.database import Base
from cloudops_agent.detection import DetectionService
from cloudops_agent.models import Incident
from cloudops_agent.schemas import MetricEvaluationRequest

POSTGRES_TEST_URL = os.getenv(
    "TEST_POSTGRES_URL",
    "postgresql+psycopg://cloudops:cloudops@localhost:55432/cloudops_test?connect_timeout=2",
)


def test_incident_persists_in_postgresql() -> None:
    postgres_engine = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    try:
        with postgres_engine.connect():
            pass
    except OperationalError:
        pytest.skip("local cloudops_test PostgreSQL database is not available")

    Base.metadata.create_all(postgres_engine)
    source = f"postgres-test-{uuid.uuid4()}"
    incident_id: uuid.UUID
    try:
        with Session(postgres_engine, expire_on_commit=False) as session:
            result = DetectionService(session).evaluate(
                MetricEvaluationRequest(
                    source=source,
                    metric_name="cpu_usage_percent",
                    value=92,
                    threshold=85,
                    timestamp=datetime.now(UTC),
                )
            )
            assert result.incident is not None
            incident_id = result.incident.id

        with Session(postgres_engine) as session:
            persisted = session.scalar(select(Incident).where(Incident.id == incident_id))
            assert persisted is not None
            assert persisted.source == source
            session.delete(persisted)
            session.commit()
    finally:
        postgres_engine.dispose()
