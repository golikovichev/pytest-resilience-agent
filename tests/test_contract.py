"""Tests for declarative resilience contracts.

A Contract states what the agent owes the caller when a dependency breaks:
it responds, it names the fallback it took, it surfaces a clear error, and it
stays under a latency bound. The plugin checks the contract against the calls
recorded by the gateway client, so a resilience test declares the invariant
once instead of repeating the same asserts in every test.
"""

from __future__ import annotations

from pytest_resilience_agent import ChatReply, Contract
from pytest_resilience_agent.contract import CallRecord


def _ok(
    content: str = "hi",
    model: str = "gateway-default",
    requested: str = "gateway-default",
    elapsed: float = 0.01,
) -> CallRecord:
    """A recorded call that returned a reply."""
    return CallRecord(
        model_requested=requested,
        reply=ChatReply(content=content, model=model, raw={}),
        elapsed=elapsed,
        error=None,
    )


def _failed(
    error: Exception | None, elapsed: float = 0.01, requested: str = "gateway-default"
) -> CallRecord:
    """A recorded call that produced no usable reply."""
    return CallRecord(model_requested=requested, reply=None, elapsed=elapsed, error=error)


class TestResponds:
    def test_passes_when_a_call_returned_content(self) -> None:
        contract = Contract(responds=True)
        assert contract.check([_ok(content="here is your answer")]) == []

    def test_fails_when_no_call_returned_content(self) -> None:
        contract = Contract(responds=True)
        violations = contract.check([_ok(content="")])
        assert len(violations) == 1
        assert "responds" in violations[0]

    def test_fails_when_gateway_never_called(self) -> None:
        contract = Contract(responds=True)
        violations = contract.check([])
        assert len(violations) == 1
        assert "never called" in violations[0]


class TestNamesFallback:
    def test_passes_when_a_reply_came_from_a_different_model(self) -> None:
        contract = Contract(names_fallback=True)
        call = _ok(model="backup-model", requested="primary-model")
        assert contract.check([call]) == []

    def test_fails_when_every_reply_came_from_the_requested_model(self) -> None:
        contract = Contract(names_fallback=True)
        call = _ok(model="primary-model", requested="primary-model")
        violations = contract.check([call])
        assert len(violations) == 1
        assert "names_fallback" in violations[0]


class TestSurfacesClearError:
    def test_passes_when_an_empty_reply_is_paired_with_a_raised_error(self) -> None:
        contract = Contract(surfaces_clear_error=True)
        assert contract.check([_failed(error=RuntimeError("gateway 502"))]) == []

    def test_fails_on_a_silent_empty_reply_with_no_error(self) -> None:
        contract = Contract(surfaces_clear_error=True)
        violations = contract.check([_failed(error=None)])
        assert len(violations) == 1
        assert "surfaces_clear_error" in violations[0]

    def test_passes_when_all_calls_returned_content(self) -> None:
        contract = Contract(surfaces_clear_error=True)
        assert contract.check([_ok(content="answer")]) == []


class TestLatencyUnder:
    def test_passes_when_every_call_is_within_the_bound(self) -> None:
        contract = Contract(latency_under=2.0)
        assert contract.check([_ok(elapsed=0.5), _ok(elapsed=1.9)]) == []

    def test_fails_when_a_call_exceeds_the_bound(self) -> None:
        contract = Contract(latency_under=2.0)
        violations = contract.check([_ok(elapsed=0.5), _ok(elapsed=3.1)])
        assert len(violations) == 1
        assert "latency_under" in violations[0]
        assert "3.1" in violations[0] or "3.100" in violations[0]


class TestMultipleClauses:
    def test_reports_each_independent_violation(self) -> None:
        contract = Contract(responds=True, latency_under=1.0)
        # empty content (fails responds) and slow (fails latency), one call
        call = _ok(content="", elapsed=2.0)
        violations = contract.check([call])
        assert len(violations) == 2

    def test_empty_contract_checks_nothing(self) -> None:
        # A contract with no clauses set still requires at least one call, but
        # asserts nothing about it.
        assert Contract().check([_ok()]) == []
