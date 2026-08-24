"""Create the local incident queue and its dead-letter queue."""

import json

import boto3

REGION = "us-east-1"
ACCOUNT_ID = "000000000000"

sqs = boto3.client(
    "sqs",
    endpoint_url="http://localhost:4566",
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

dlq_url = sqs.create_queue(QueueName="cloudops-incidents-dlq")["QueueUrl"]
dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])[
    "Attributes"
]["QueueArn"]

queue_url = sqs.create_queue(QueueName="cloudops-incidents")["QueueUrl"]
sqs.set_queue_attributes(
    QueueUrl=queue_url,
    Attributes={
        "RedrivePolicy": json.dumps(
            {
                "deadLetterTargetArn": dlq_arn,
                "maxReceiveCount": "3",
            }
        )
    },
)

print(f"Created incident queue {queue_url} with DLQ {dlq_arn}")

