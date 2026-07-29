"""Property-based timing fuzzing.

These tests fuzz the *simulated* timing/count parameters that gateway
scenarios already model (how many transient failures precede recovery, the
Retry-After the gateway advertises, the documented stall duration) instead of
one hand-picked value. The invariant under test: whatever timing profile
Hypothesis draws, a fuzzed transient-failure route fails exactly the first
``fail_first_n`` calls and then recovers, so a caller that retries past that
count always succeeds.

Consistent with the rest of the suite, nothing here sleeps: ``stall_seconds``
is recorded as metadata only, never awaited, so the property tests stay fast.
"""

from __future__ import annotations

import dataclasses

import httpx
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from pytest_resilience_agent.timing import (
    FuzzedTransientFailure,
    TimingProfile,
    timing_profiles,
)

TARGET = "https://gateway.local/v1/chat/completions"

# The property tests below drive real httpx through a respx MockRouter that is
# started and stopped per example. That transport setup costs a few hundred ms
# and is not the behaviour under test, so we disable Hypothesis's per-example
# deadline and cap the example count: enough profiles to sweep the space, fast
# enough to keep CI green and non-flaky.
_TRANSPORT_FUZZ = settings(deadline=None, max_examples=30)


def _drive(profile: TimingProfile) -> list[int]:
    """Apply the fuzzed route and return the status of fail_first_n + 2 calls.

    Two calls past the failure window prove recovery is stable, not a one-shot
    flip at the boundary.
    """
    mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
    mock.start()
    scenario = FuzzedTransientFailure(mock, TARGET, profile)
    scenario.apply()
    try:
        with httpx.Client() as client:
            return [
                client.post(TARGET, json={"q": i}).status_code
                for i in range(profile.fail_first_n + 2)
            ]
    finally:
        scenario.revert()
        mock.stop()


def test_timing_profile_is_frozen_dataclass() -> None:
    profile = TimingProfile(fail_first_n=1, retry_after_seconds=2, stall_seconds=5.0)
    assert dataclasses.is_dataclass(profile)
    assert profile.fail_first_n == 1
    assert profile.retry_after_seconds == 2
    assert profile.stall_seconds == 5.0
    # frozen: attributes cannot be mutated
    try:
        profile.fail_first_n = 9  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - guards the frozen contract
        raise AssertionError("TimingProfile must be frozen")


@given(profile=timing_profiles())
def test_strategy_draws_profiles_within_default_bounds(profile: TimingProfile) -> None:
    assert isinstance(profile, TimingProfile)
    assert 0 <= profile.fail_first_n <= 3
    assert 0 <= profile.retry_after_seconds <= 10
    assert 0.0 <= profile.stall_seconds <= 60.0


@given(profile=timing_profiles(max_fail_first_n=6, max_retry_after_seconds=30))
def test_strategy_honours_custom_bounds(profile: TimingProfile) -> None:
    assert 0 <= profile.fail_first_n <= 6
    assert 0 <= profile.retry_after_seconds <= 30


@_TRANSPORT_FUZZ
@given(profile=timing_profiles())
def test_fuzzed_failure_recovers_after_fail_first_n(profile: TimingProfile) -> None:
    """For any drawn profile: first fail_first_n calls fail, then stays recovered."""
    statuses = _drive(profile)
    assert statuses[: profile.fail_first_n] == [429] * profile.fail_first_n
    # Every call past the failure window recovers, not just the boundary call.
    assert statuses[profile.fail_first_n :] == [200, 200]


@_TRANSPORT_FUZZ
@given(retry_after=st.integers(min_value=0, max_value=10))
def test_fuzzed_failure_advertises_drawn_retry_after(retry_after: int) -> None:
    """The 429 responses carry the profile's Retry-After header verbatim."""
    profile = TimingProfile(fail_first_n=1, retry_after_seconds=retry_after, stall_seconds=0.0)
    mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
    mock.start()
    scenario = FuzzedTransientFailure(mock, TARGET, profile)
    scenario.apply()
    try:
        with httpx.Client() as client:
            first = client.post(TARGET, json={"q": 1})
            assert first.status_code == 429
            assert first.headers.get("Retry-After") == str(retry_after)
    finally:
        scenario.revert()
        mock.stop()


def test_zero_failures_recovers_immediately() -> None:
    profile = TimingProfile(fail_first_n=0, retry_after_seconds=0, stall_seconds=0.0)
    statuses = _drive(profile)
    assert statuses == [200, 200]


def test_timing_profiles_rejects_negative_bounds() -> None:
    """Negative bounds are a usage error, not a silently empty search space."""
    import pytest

    for kwargs in (
        {"max_fail_first_n": -1},
        {"max_retry_after_seconds": -1},
        {"max_stall_seconds": -1.0},
    ):
        with pytest.raises(ValueError):
            timing_profiles(**kwargs)


def test_apply_records_timing_metadata() -> None:
    """stall_seconds is documented in metadata, never awaited."""
    profile = TimingProfile(fail_first_n=2, retry_after_seconds=3, stall_seconds=42.0)
    mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
    mock.start()
    scenario = FuzzedTransientFailure(mock, TARGET, profile)
    result = scenario.apply()
    try:
        assert result.metadata["fail_first_n"] == 2
        assert result.metadata["retry_after_seconds"] == 3
        assert result.metadata["stall_seconds"] == 42.0
    finally:
        scenario.revert()
        mock.stop()


def test_revert_reports_calls_intercepted() -> None:
    profile = TimingProfile(fail_first_n=1, retry_after_seconds=1, stall_seconds=0.0)
    mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
    mock.start()
    scenario = FuzzedTransientFailure(mock, TARGET, profile)
    scenario.apply()
    with httpx.Client() as client:
        client.post(TARGET, json={"q": 1})
        client.post(TARGET, json={"q": 2})
    result = scenario.revert()
    mock.stop()
    assert result.metadata["calls_intercepted"] == 2
