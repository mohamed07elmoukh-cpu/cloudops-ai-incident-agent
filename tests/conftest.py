from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import app
from cloudops_agent.database import Base, get_session


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as test_session:
        yield test_session


@pytest.fixture
def client(engine: Engine) -> Generator[TestClient, None, None]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with factory() as test_session:
            yield test_session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

