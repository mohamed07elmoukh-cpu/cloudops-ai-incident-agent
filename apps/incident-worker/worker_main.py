"""Executable entrypoint for the SQS incident worker."""

from __future__ import annotations

import logging
import os
import signal
import threading
from collections.abc import Callable

import uvicorn

from cloudops_agent.adapters.aws import CloudWatchAlarmTagResolver
from cloudops_agent.database import SessionLocal, engine
from cloudops_agent.events.cloudwatch import decode_event_message
from cloudops_agent.events.consumer import IncidentWorker, WorkerLoopState
from cloudops_agent.events.health import create_worker_health_app
from cloudops_agent.events.models import CloudEventEnvelope
from cloudops_agent.events.queue import SqsEventQueue


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop_event = threading.Event()
    state = WorkerLoopState()
    queue = SqsEventQueue.from_environment()
    correlation_tag = os.getenv("AWS_CORRELATION_TAG_KEY")
    event_decoder: Callable[[str], CloudEventEnvelope] | None = None
    if correlation_tag:
        resolver = CloudWatchAlarmTagResolver(correlation_tag)

        def decode_with_alarm_tags(body: str) -> CloudEventEnvelope:
            return decode_event_message(body, resolver.resolve)

        event_decoder = decode_with_alarm_tags
    worker = IncidentWorker(queue, SessionLocal, state=state, event_decoder=event_decoder)
    health_app = create_worker_health_app(queue, state, engine)
    server = uvicorn.Server(uvicorn.Config(health_app, host="0.0.0.0", port=8002, log_level="info"))
    health_thread = threading.Thread(target=server.run, name="worker-health", daemon=True)

    def request_shutdown(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    health_thread.start()
    try:
        worker.run(stop_event)
    finally:
        server.should_exit = True
        health_thread.join(timeout=5)


if __name__ == "__main__":
    main()
