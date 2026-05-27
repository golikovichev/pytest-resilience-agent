"""Smoke tests for the plugin's marker and fixtures.

These tests cover the public surface that the rest of the suite (and
end-user tests) depend on. They do not require a real gateway or Lark
instance: the fixtures skip cleanly when no URL is configured.
"""

from __future__ import annotations

import pytest

from pytest_resilience_agent.chaos import ChaosController


def test_resilience_marker_registered(pytestconfig: pytest.Config) -> None:
    """The plugin's pytest_configure adds the marker so --strict-markers passes."""
    markers = pytestconfig.getini("markers")
    assert any(m.startswith("resilience(") for m in markers), markers


def test_chaos_controller_records_enter_and_exit() -> None:
    """ChaosController records lifecycle events for the scenarios it was given."""
    controller = ChaosController(scenarios=["llm_timeout", "rate_limit"])
    controller.enter()
    try:
        applied = [e.scenario for e in controller.events]
        assert "llm_timeout" in applied
        assert "rate_limit" in applied
    finally:
        controller.exit()
    removed = [e for e in controller.events if e.detail == "scenario removed"]
    assert {e.scenario for e in removed} == {"llm_timeout", "rate_limit"}


def test_chaos_controller_rejects_unknown_scenario() -> None:
    """An unknown scenario name surfaces as ValueError, not silent no-op."""
    import pytest as _pt

    controller = ChaosController(scenarios=["does_not_exist"])
    with _pt.raises(ValueError, match="unknown chaos scenario"):
        controller.enter()
    # respx mock leaked - clean it up so other tests in the same session work
    try:
        controller._mock.stop()
    except Exception:
        pass


def test_ai_gateway_fixture_skips_without_config(
    pytester: pytest.Pytester,
) -> None:
    """When no gateway URL is configured the fixture skips rather than blowing up."""
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.resilience(scenarios=["llm_timeout"])
        def test_uses_gateway(ai_gateway, chaos):
            assert False, "should have skipped before reaching the body"
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(skipped=1)
