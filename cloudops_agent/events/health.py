"""HTTP health and metrics surface for the incident worker."""

from __future__ import annotations

from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import Engine, text

from cloudops_agent.events.consumer import WorkerLoopState
from cloudops_agent.events.metrics import WORKER_REGISTRY
from cloudops_agent.events.queue import EventQueue


def create_worker_health_app(
    queue: EventQueue, state: WorkerLoopState, database_engine: Engine
) -> FastAPI:
    app = FastAPI(title="CloudOps Incident Worker", version="0.1.0")

    @app.get("/health")
    def health(response: Response) -> dict[str, bool | str]:
        database_ok = False
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database_ok = True
        except Exception:
            database_ok = False
        sqs_ok = queue.health()
        loop_ok = state.healthy()
        healthy = database_ok and sqs_ok and loop_ok
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "unhealthy",
            "database": database_ok,
            "sqs": sqs_ok,
            "consumer_loop": loop_ok,
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(
            content=generate_latest(WORKER_REGISTRY), media_type=CONTENT_TYPE_LATEST
        )

    return app

