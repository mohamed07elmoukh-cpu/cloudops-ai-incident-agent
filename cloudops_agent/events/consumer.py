"""Bounded SQS polling loop for normalized incident events."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from cloudops_agent.events.metrics import (
    EVENT_PROCESSING_SECONDS,
    EVENTS_DUPLICATE,
    EVENTS_FAILED,
    EVENTS_PROCESSED,
    EVENTS_RECEIVED,
    INCIDENTS_CREATED,
)
from cloudops_agent.events.models import CloudEventEnvelope
from cloudops_agent.events.processor import IncidentEventProcessor
from cloudops_agent.events.queue import EventQueue, QueueMessage

LOGGER = logging.getLogger(__name__)


class WorkerLoopState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = False
        self._last_heartbeat = 0.0

    def heartbeat(self) -> None:
        with self._lock:
            self._started = True
            self._last_heartbeat = time.monotonic()

    def healthy(self, max_age_seconds: float = 30.0) -> bool:
        with self._lock:
            return self._started and time.monotonic() - self._last_heartbeat <= max_age_seconds


class IncidentWorker:
    def __init__(
        self,
        queue: EventQueue,
        session_factory: Callable[[], Session],
        processor: IncidentEventProcessor | None = None,
        state: WorkerLoopState | None = None,
        batch_size: int = 5,
    ) -> None:
        self.queue = queue
        self.session_factory = session_factory
        self.processor = processor or IncidentEventProcessor()
        self.state = state or WorkerLoopState()
        self.batch_size = max(1, min(batch_size, 10))

    def process_message(self, message: QueueMessage) -> bool:
        EVENTS_RECEIVED.inc()
        started = time.monotonic()
        try:
            event = CloudEventEnvelope.model_validate_json(message.body)
            with self.session_factory() as session:
                result = self.processor.process(event, session)
            if result.duplicate:
                EVENTS_DUPLICATE.inc()
            else:
                EVENTS_PROCESSED.inc()
                if result.incident_created:
                    INCIDENTS_CREATED.inc()
            self.queue.delete(message.receipt_handle)
            return True
        except Exception:
            EVENTS_FAILED.inc()
            LOGGER.exception(
                "event processing failed; leaving message for redrive",
                extra={"message_id": message.message_id, "receive_count": message.receive_count},
            )
            return False
        finally:
            EVENT_PROCESSING_SECONDS.observe(time.monotonic() - started)

    def run_once(self, wait_time_seconds: int = 10) -> int:
        self.state.heartbeat()
        messages = self.queue.receive(self.batch_size, wait_time_seconds)
        for message in messages:
            self.process_message(message)
        self.state.heartbeat()
        return len(messages)

    def run(self, stop_event: threading.Event) -> None:
        self.state.heartbeat()
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                EVENTS_FAILED.inc()
                LOGGER.exception("bounded worker polling iteration failed")
                stop_event.wait(1.0)
