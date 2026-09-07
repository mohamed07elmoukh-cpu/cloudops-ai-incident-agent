from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from cloudops_agent.detection import DetectionService
from cloudops_agent.schemas import ResourceMetricEvaluationRequest


def signal(
    resource_type: str, resource_id: str, metric_name: str
) -> ResourceMetricEvaluationRequest:
    return ResourceMetricEvaluationRequest(
        resource_type=resource_type,
        resource_id=resource_id,
        metric_name=metric_name,
        value=92,
        threshold=80,
        timestamp=datetime.now(UTC),
        correlation_group="service:checkout",
    )


def test_correlates_three_aws_services_and_refreshes_evidence_diagnosis(
    session: Session,
) -> None:
    detection = DetectionService(session)
    ec2 = detection.evaluate_resource(signal("EC2", "checkout-asg", "CPUUtilization"))
    dynamodb = detection.evaluate_resource(
        signal("DYNAMODB", "checkout-orders", "ReadThrottleEvents")
    )
    rds = detection.evaluate_resource(signal("RDS", "checkout-db", "CPUUtilization"))

    incidents = [ec2.incident, dynamodb.incident, rds.incident]
    assert all(incident is not None for incident in incidents)
    for incident in incidents:
        assert incident is not None
        session.refresh(incident)
        assert incident.correlation_group == "service:checkout"
        assert incident.diagnosis_confidence == 0.89
        assert len(incident.diagnosis_evidence) == 3
        assert "rule-based" in str(incident.diagnosis_summary)
    assert dynamodb.incident is not None
    assert "DynamoDB throttling" in str(dynamodb.incident.probable_root_cause)
