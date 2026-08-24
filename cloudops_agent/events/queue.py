"""Queue boundary with SQS and deterministic in-memory implementations."""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config

from cloudops_agent.events.models import CloudEventEnvelope


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    receipt_handle: str
    body: str
    receive_count: int


class EventQueue(ABC):
    @abstractmethod
    def publish(self, event: CloudEventEnvelope) -> str:
        """Publish one normalized event and return the provider message ID."""

    @abstractmethod
    def receive(
        self, max_messages: int = 5, wait_time_seconds: int = 10
    ) -> list[QueueMessage]:
        """Long poll a bounded batch of events."""

    @abstractmethod
    def delete(self, receipt_handle: str) -> None:
        """Acknowledge a successfully committed event."""

    @abstractmethod
    def health(self) -> bool:
        """Check that the queue backend is reachable."""

    @abstractmethod
    def approximate_counts(self) -> tuple[int, int]:
        """Return visible and in-flight message counts."""


class SqsClientProtocol(Protocol):
    def send_message(self, **kwargs: Any) -> dict[str, Any]: ...

    def receive_message(self, **kwargs: Any) -> dict[str, Any]: ...

    def delete_message(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_queue_attributes(self, **kwargs: Any) -> dict[str, Any]: ...


class SqsEventQueue(EventQueue):
    def __init__(
        self,
        queue_url: str,
        client: SqsClientProtocol | None = None,
        visibility_timeout: int = 30,
    ) -> None:
        if not queue_url:
            raise ValueError("queue_url is required")
        self.queue_url = queue_url
        self.client = client or self._build_client()
        self.visibility_timeout = max(0, min(visibility_timeout, 43_200))

    @staticmethod
    def _build_client() -> SqsClientProtocol:
        config = Config(
            connect_timeout=2,
            read_timeout=15,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        return cast(
            SqsClientProtocol,
            boto3.client(
                "sqs",
                endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
                region_name=os.getenv("AWS_REGION", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
                config=config,
            ),
        )

    @classmethod
    def from_environment(cls) -> SqsEventQueue:
        return cls(os.environ["INCIDENT_QUEUE_URL"])

    def publish(self, event: CloudEventEnvelope) -> str:
        response = self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=event.model_dump_json(),
            MessageAttributes={
                "event_type": {"DataType": "String", "StringValue": event.event_type},
                "trace_id": {"DataType": "String", "StringValue": str(event.trace_id)},
            },
        )
        return str(response["MessageId"])

    def receive(
        self, max_messages: int = 5, wait_time_seconds: int = 10
    ) -> list[QueueMessage]:
        response = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max(1, min(max_messages, 10)),
            WaitTimeSeconds=max(0, min(wait_time_seconds, 20)),
            VisibilityTimeout=self.visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
        )
        return [
            QueueMessage(
                message_id=str(item["MessageId"]),
                receipt_handle=str(item["ReceiptHandle"]),
                body=str(item["Body"]),
                receive_count=int(item.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
            )
            for item in response.get("Messages", [])
        ]

    def delete(self, receipt_handle: str) -> None:
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)

    def health(self) -> bool:
        try:
            self.client.get_queue_attributes(QueueUrl=self.queue_url, AttributeNames=["QueueArn"])
        except Exception:
            return False
        return True

    def approximate_counts(self) -> tuple[int, int]:
        response = self.client.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )
        attributes = response.get("Attributes", {})
        return (
            int(attributes.get("ApproximateNumberOfMessages", 0)),
            int(attributes.get("ApproximateNumberOfMessagesNotVisible", 0)),
        )


class InMemoryEventQueue(EventQueue):
    """Small deterministic queue used only by unit and API tests."""

    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []
        self.deleted_receipts: list[str] = []

    def publish(self, event: CloudEventEnvelope) -> str:
        message_id = str(uuid.uuid4())
        self.messages.append(
            QueueMessage(
                message_id=message_id,
                receipt_handle=str(uuid.uuid4()),
                body=event.model_dump_json(),
                receive_count=1,
            )
        )
        return message_id

    def publish_raw(self, body: str) -> str:
        message_id = str(uuid.uuid4())
        self.messages.append(
            QueueMessage(
                message_id=message_id,
                receipt_handle=str(uuid.uuid4()),
                body=body,
                receive_count=1,
            )
        )
        return message_id

    def receive(
        self, max_messages: int = 5, wait_time_seconds: int = 10
    ) -> list[QueueMessage]:
        del wait_time_seconds
        deleted = set(self.deleted_receipts)
        return [item for item in self.messages if item.receipt_handle not in deleted][:max_messages]

    def delete(self, receipt_handle: str) -> None:
        self.deleted_receipts.append(receipt_handle)

    def health(self) -> bool:
        return True

    def approximate_counts(self) -> tuple[int, int]:
        deleted = set(self.deleted_receipts)
        visible = sum(item.receipt_handle not in deleted for item in self.messages)
        return visible, 0
