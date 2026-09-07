"""Resolve application correlation keys from CloudWatch alarm tags."""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.config import Config


class CloudWatchAlarmTagResolver:
    """Read one configured tag from a CloudWatch alarm ARN."""

    def __init__(self, tag_key: str, cloudwatch_client: Any | None = None) -> None:
        if not tag_key.strip():
            raise ValueError("CloudWatch correlation tag key cannot be empty")
        self.tag_key = tag_key
        self.cloudwatch = cloudwatch_client or boto3.client(
            "cloudwatch",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            endpoint_url=os.getenv("CLOUDWATCH_ALARM_ENDPOINT_URL"),
            config=Config(
                ignore_configured_endpoint_urls=True  # type: ignore[call-arg]
            ),
        )

    def resolve(self, alarm_arn: str) -> str | None:
        response = self.cloudwatch.list_tags_for_resource(ResourceARN=alarm_arn)
        for tag in response.get("Tags", []):
            if tag.get("Key") == self.tag_key:
                value = str(tag.get("Value", "")).strip()
                return value or None
        return None
