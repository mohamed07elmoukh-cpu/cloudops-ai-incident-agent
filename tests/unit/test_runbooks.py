from pathlib import Path

import pytest

from cloudops_agent.remediation.runbooks import InvalidRunbookError, RunbookLoader


def test_invalid_runbook_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text(
        "name: broken\nversion: '1.0'\nincident_types: []\n",
        encoding="utf-8",
    )

    with pytest.raises(InvalidRunbookError):
        RunbookLoader(tmp_path).load("broken")


def test_scale_service_runbook_loads() -> None:
    runbook = RunbookLoader().load("scale_service")

    assert runbook.name == "scale_service"
    assert "CPU_SATURATION" in runbook.incident_types
    assert runbook.verification.threshold == 70
    assert runbook.verification.max_attempts == 3


@pytest.mark.parametrize(
    ("name", "incident_type", "approval_required"),
    [
        ("scale_ec2_auto_scaling_group", "EC2_CAPACITY_SATURATION", False),
        ("scale_dynamodb_capacity", "DYNAMODB_CAPACITY_SATURATION", False),
        ("scale_rds_storage", "RDS_STORAGE_LOW", False),
        ("scale_rds_compute", "RDS_COMPUTE_SATURATION", True),
    ],
)
def test_aws_capacity_runbooks_load(
    name: str, incident_type: str, approval_required: bool
) -> None:
    runbook = RunbookLoader().load(name)

    assert runbook.executor == "aws"
    assert incident_type in runbook.incident_types
    assert runbook.approval_required is approval_required
    assert runbook.cooldown_seconds > 0
    assert runbook.max_monthly_cost_delta_usd > 0
