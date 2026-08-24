from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient


def load_faulty_service() -> ModuleType:
    service_path = Path(__file__).resolve().parents[2] / "demo" / "faulty-service" / "main.py"
    spec = importlib.util.spec_from_file_location("faulty_service_main", service_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_faulty_service_health_metrics_and_error_injection() -> None:
    module = load_faulty_service()
    service_app = module.app
    assert isinstance(service_app, FastAPI)

    with TestClient(service_app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/work").status_code == 200
        assert client.post("/chaos/errors?enabled=true").status_code == 200
        assert client.get("/work").status_code == 500
        assert client.post("/chaos/errors?enabled=false").status_code == 200
        metrics = client.get("/metrics").text

    assert "demo_cpu_load_percent" in metrics
    assert "demo_http_requests_total" in metrics
    assert "demo_http_errors_total" in metrics
    assert "demo_service_healthy" in metrics


def test_cpu_chaos_duration_is_bounded_and_returns_immediately() -> None:
    module = load_faulty_service()
    service_app = module.app

    with TestClient(service_app) as client:
        assert client.post("/chaos/cpu?duration_seconds=0").status_code == 422
        assert client.post("/chaos/cpu?duration_seconds=181").status_code == 422
        assert client.post("/chaos/cpu?duration_seconds=1").status_code == 202
        assert client.get("/health").status_code == 200

