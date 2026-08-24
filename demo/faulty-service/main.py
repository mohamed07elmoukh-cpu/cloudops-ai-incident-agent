"""Deliberately faulty FastAPI service used by the local incident demo."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)
from starlette.responses import JSONResponse

app = FastAPI(title="CloudOps Faulty Service", version="0.1.0")

METRICS_REGISTRY = CollectorRegistry()
CPU_LOAD = Gauge(
    "demo_cpu_load_percent", "Simulated CPU load percentage", registry=METRICS_REGISTRY
)
HTTP_REQUESTS = Counter(
    "demo_http_requests_total", "Total HTTP requests", registry=METRICS_REGISTRY
)
HTTP_ERRORS = Counter(
    "demo_http_errors_total", "Total HTTP 5xx responses", registry=METRICS_REGISTRY
)
SERVICE_HEALTHY = Gauge(
    "demo_service_healthy", "Whether the demo service is healthy", registry=METRICS_REGISTRY
)
SERVICE_HEALTHY.set(1)

_state_lock = threading.Lock()
_errors_enabled = False
_active_cpu_jobs = 0
_background_tasks: set[asyncio.Task[None]] = set()


@app.middleware("http")
async def record_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    HTTP_REQUESTS.inc()
    try:
        response = await call_next(request)
    except Exception:
        HTTP_ERRORS.inc()
        raise
    if response.status_code >= 500:
        HTTP_ERRORS.inc()
    return response


@app.get("/health")
def health() -> dict[str, bool | str]:
    with _state_lock:
        healthy = not _errors_enabled
    return {"status": "ok", "healthy": healthy}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(METRICS_REGISTRY), media_type=CONTENT_TYPE_LATEST)


def _burn_cpu(duration_seconds: int) -> None:
    global _active_cpu_jobs
    with _state_lock:
        _active_cpu_jobs += 1
        CPU_LOAD.set(100)
    deadline = time.monotonic() + duration_seconds
    accumulator = 0
    try:
        while time.monotonic() < deadline:
            accumulator = (accumulator * 33 + 17) % 1_000_003
    finally:
        with _state_lock:
            _active_cpu_jobs -= 1
            if _active_cpu_jobs == 0:
                CPU_LOAD.set(0)
        _ = accumulator


@app.post("/chaos/cpu", status_code=202)
async def start_cpu_chaos(
    duration_seconds: int = Query(default=60, ge=1, le=180),
) -> dict[str, int | str]:
    task = asyncio.create_task(asyncio.to_thread(_burn_cpu, duration_seconds))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started", "duration_seconds": duration_seconds}


@app.post("/chaos/errors")
def configure_errors(enabled: bool = Query(default=True)) -> dict[str, bool]:
    global _errors_enabled
    with _state_lock:
        _errors_enabled = enabled
        SERVICE_HEALTHY.set(0 if enabled else 1)
    return {"errors_enabled": enabled}


@app.get("/work")
def work() -> JSONResponse:
    with _state_lock:
        errors_enabled = _errors_enabled
    if errors_enabled:
        raise HTTPException(status_code=500, detail="injected demo error")
    return JSONResponse({"status": "completed"})
