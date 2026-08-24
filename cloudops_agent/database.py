"""Database engine and session management."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://cloudops:cloudops@postgres:5432/cloudops"


class Base(DeclarativeBase):
    """Declarative base shared by all persistence models."""


def build_engine(database_url: str | None = None) -> Engine:
    """Build an SQLAlchemy engine for PostgreSQL or the SQLite test adapter."""
    url = database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    """Yield one transaction-scoped database session for FastAPI."""
    with SessionLocal() as session:
        yield session
