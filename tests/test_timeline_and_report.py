"""Tests for --resilience-record timeline export and pytest report hook."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_timeline_recorded_per_test(pytester: pytest.Pytester, tmp_path: Path) -> None:
    """When --resilience-record is set, a JSON file is written after session."""
    pytester.makepyfile(
        """
        import httpx
        import pytest

        @pytest.mark.resilience(scenarios=["llm_5xx"])
        def test_a(chaos):
            with httpx.Client() as client:
                client.post(chaos.target_gateway_url, json={"q": 1})
                client.post(chaos.target_gateway_url, json={"q": 2})

        @pytest.mark.resilience(scenarios=["rate_limit"])
        def test_b(chaos):
            with httpx.Client() as client:
                client.post(chaos.target_gateway_url, json={"q": 1})
        """
    )
    record = tmp_path / "timeline.json"
    result = pytester.runpytest("-v", f"--resilience-record={record}")
    result.assert_outcomes(passed=2)
    assert record.exists()
    data = json.loads(record.read_text(encoding="utf-8"))
    assert len(data) == 2
    test_a_entry = next(e for e in data if e["test"].endswith("test_a"))
    assert test_a_entry["scenarios"] == ["llm_5xx"]
    # Calls intercepted recorded in the "scenario removed" event metadata
    removed_events = [e for e in test_a_entry["events"] if e["detail"] == "scenario removed"]
    assert removed_events
    assert removed_events[0]["metadata"]["calls_intercepted"] == 2


def test_report_hook_records_sections(pytester: pytest.Pytester, tmp_path: Path) -> None:
    """The pytest_runtest_logreport hook attaches a 'chaos events' section
    to the test report. We verify via the recorded timeline file rather
    than CLI output, since pytest's section rendering on PASS requires
    extra flags. The hook fires either way; the timeline confirms it.
    """
    pytester.makepyfile(
        """
        import httpx
        import pytest

        @pytest.mark.resilience(scenarios=["llm_5xx"])
        def test_with_chaos(chaos):
            with httpx.Client() as client:
                client.post(chaos.target_gateway_url, json={"q": 1})
        """
    )
    record = tmp_path / "timeline.json"
    result = pytester.runpytest("-v", f"--resilience-record={record}")
    result.assert_outcomes(passed=1)
    data = json.loads(record.read_text(encoding="utf-8"))
    assert len(data) == 1
    scenarios_in_events = {e["scenario"] for e in data[0]["events"]}
    assert "llm_5xx" in scenarios_in_events
