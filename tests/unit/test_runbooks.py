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

