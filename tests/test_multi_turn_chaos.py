"""Multi-turn chaos: chaos bound to a conversation turn, advanced with next_turn().

These drive the controller directly with httpx against the mocked gateway URL,
the same smoking-gun style as test_chaos_scenarios.py.
"""

from __future__ import annotations

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pytest_resilience_agent.chaos import ChaosController


def test_chaos_swaps_between_turns_with_fresh_counters() -> None:
    """turn 0 runs llm_5xx (first call 502); after next_turn() turn 1 runs
    rate_limit with a FRESH counter (first call 429, not carried over)."""
    controller = ChaosController(turns=[["llm_5xx"], ["rate_limit"]])
    controller.enter()
    try:
        with httpx.Client() as client:
            r0 = client.post(controller.target_gateway_url, json={"q": 1})
            assert r0.status_code == 502  # llm_5xx first call of turn 0

            controller.next_turn()

            r1 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r1.status_code == 429  # rate_limit first call of turn 1 (fresh)
    finally:
        controller.exit()


def test_next_turn_past_last_turn_raises_usage_error() -> None:
    """Advancing beyond the last defined turn is a test-author error, not silent."""
    controller = ChaosController(turns=[["llm_5xx"]])
    controller.enter()
    try:
        with pytest.raises(pytest.UsageError):
            controller.next_turn()
    finally:
        controller.exit()


def test_turns_and_scenarios_together_raise_usage_error() -> None:
    """`turns=` and `scenarios=` are mutually exclusive; both is a usage error."""
    with pytest.raises(pytest.UsageError):
        ChaosController(scenarios=["llm_5xx"], turns=[["rate_limit"]])


def test_current_turn_tracks_index() -> None:
    """current_turn starts at 0 and advances by one per next_turn()."""
    controller = ChaosController(turns=[[], ["llm_5xx"], []])
    controller.enter()
    try:
        assert controller.current_turn == 0
        controller.next_turn()
        assert controller.current_turn == 1
        controller.next_turn()
        assert controller.current_turn == 2
    finally:
        controller.exit()


def test_empty_turns_list_raises_usage_error() -> None:
    """turns=[] is an author mistake (no turns to run) -> clear error, not IndexError."""
    with pytest.raises(pytest.UsageError):
        ChaosController(turns=[])


def test_unknown_scenario_in_a_turn_raises_usage_error_up_front() -> None:
    """A typo in any turn surfaces at construction, not mid-conversation."""
    with pytest.raises(pytest.UsageError):
        ChaosController(turns=[["llm_5xx"], ["does_not_exist"]])


def test_next_turn_without_turns_mode_raises_usage_error() -> None:
    """Calling next_turn() on a single-window (scenarios=) controller is an error."""
    controller = ChaosController(scenarios=["llm_5xx"])
    controller.enter()
    try:
        with pytest.raises(pytest.UsageError):
            controller.next_turn()
    finally:
        controller.exit()


def test_call_counter_resets_in_recorded_events_per_turn() -> None:
    """The revert event of each turn records calls scoped to that turn only."""
    controller = ChaosController(turns=[["llm_5xx"], ["llm_5xx"]])
    controller.enter()
    try:
        with httpx.Client() as client:
            client.post(controller.target_gateway_url, json={})  # 1 call in turn 0
            controller.next_turn()
            client.post(controller.target_gateway_url, json={})  # 1 call in turn 1
            client.post(controller.target_gateway_url, json={})  # 2 calls in turn 1
    finally:
        controller.exit()
    removed = [
        e for e in controller.events if e.detail == "scenario removed" and e.scenario == "llm_5xx"
    ]
    intercepted = [e.metadata["calls_intercepted"] for e in removed]
    assert intercepted == [1, 2], intercepted  # turn 0 saw 1 call, turn 1 saw 2 (reset)


def test_each_turn_boundary_emits_an_otel_span() -> None:
    """Every turn boundary emits a chaos.turn.N span carrying that turn's scenarios."""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not hasattr(provider, "add_span_processor"):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    controller = ChaosController(turns=[["llm_5xx"], ["rate_limit"]])
    controller.enter()
    try:
        controller.next_turn()
    finally:
        controller.exit()

    names = [s.name for s in exporter.get_finished_spans()]
    assert "chaos.turn.0" in names
    assert "chaos.turn.1" in names


def test_marker_turns_drives_chaos_through_the_fixture(pytester: pytest.Pytester) -> None:
    """End-to-end: the resilience marker's turns= reaches the chaos fixture and
    next_turn() swaps chaos between conversation turns inside a real test."""
    pytester.makepyfile(
        """
        import httpx
        import pytest

        @pytest.mark.resilience(turns=[["llm_5xx"], ["rate_limit"]])
        def test_multi_turn(chaos):
            with httpx.Client() as client:
                r0 = client.post(chaos.target_gateway_url, json={})
                assert r0.status_code == 502
                chaos.next_turn()
                r1 = client.post(chaos.target_gateway_url, json={})
                assert r1.status_code == 429
        """
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=1)
