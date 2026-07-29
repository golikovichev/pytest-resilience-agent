"""Property-based timing fuzzing.

The built-in scenarios pin their timing to one hand-picked value: ``rate_limit``
advertises a fixed ``Retry-After``, the transient failures recover after a fixed
number of calls. Real gateways vary: the Retry-After the load balancer returns,
how many calls a brownout swallows before it clears, how long a stall lasts.
This module lets a test sweep that whole bounded space with Hypothesis and
assert the same invariant holds for every drawn profile, instead of trusting one
example.

Consistent with the rest of the plugin, nothing here sleeps. ``stall_seconds``
documents the simulated stall duration in the scenario metadata; it is never
awaited, so the property tests stay fast and deterministic (the same reason
``llm_timeout`` raises ``ReadTimeout`` instead of blocking).

``TimingProfile`` and ``FuzzedTransientFailure`` are pure and need no extra
dependency. ``timing_profiles`` returns a Hypothesis strategy and therefore
imports Hypothesis lazily, so installing it is only required for the fuzzing
entry point (extra: ``pytest-resilience-agent[fuzz]``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import respx

from pytest_resilience_agent.scenarios import Scenario, ScenarioResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypothesis.strategies import SearchStrategy


@dataclass(frozen=True)
class TimingProfile:
    """One drawn set of simulated timing parameters for a transient failure.

    Attributes:
        fail_first_n: How many leading calls fail before the gateway recovers.
        retry_after_seconds: The ``Retry-After`` value advertised on each 429.
        stall_seconds: Documented stall duration, recorded as metadata only.
    """

    fail_first_n: int
    retry_after_seconds: int
    stall_seconds: float


class FuzzedTransientFailure(Scenario):
    """Gateway fails the first ``profile.fail_first_n`` calls, then recovers.

    Each failure is a 429 carrying the profile's ``Retry-After``; the recovery
    call returns 200. Unlike the fixed ``rate_limit`` scenario, the failure
    count and Retry-After come from a fuzzed ``TimingProfile``, so a single
    property test exercises the whole timing space rather than one example.
    """

    name = "fuzzed_transient_failure"

    def __init__(
        self,
        mock: respx.MockRouter,
        target_url: str,
        profile: TimingProfile,
    ) -> None:
        super().__init__(mock, target_url)
        self.profile = profile

    def apply(self) -> ScenarioResult:
        success_payload = {
            "model": "primary-model",
            "choices": [{"message": {"role": "assistant", "content": "recovered"}}],
        }
        retry_after = str(self.profile.retry_after_seconds)

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            if self._calls <= self.profile.fail_first_n:
                return httpx.Response(
                    429,
                    headers={"Retry-After": retry_after},
                    text="rate limited",
                )
            return httpx.Response(200, json=success_payload)

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail=(
                f"first {self.profile.fail_first_n} call(s) return 429 "
                f"(Retry-After {retry_after}s), then recover"
            ),
            metadata={
                "fail_first_n": self.profile.fail_first_n,
                "retry_after_seconds": self.profile.retry_after_seconds,
                "stall_seconds": self.profile.stall_seconds,
            },
        )


def timing_profiles(
    *,
    max_fail_first_n: int = 3,
    max_retry_after_seconds: int = 10,
    max_stall_seconds: float = 60.0,
) -> SearchStrategy[TimingProfile]:
    """Hypothesis strategy drawing ``TimingProfile`` values within bounds.

    Use it to fuzz a transient failure over the whole timing space::

        from hypothesis import given
        from pytest_resilience_agent import (
            FuzzedTransientFailure, timing_profiles,
        )

        @given(profile=timing_profiles())
        def test_agent_recovers(profile):
            # install FuzzedTransientFailure with `profile`, then assert the
            # agent recovers past profile.fail_first_n retries.
            ...

    Raises:
        ValueError: if any bound is negative.
    """
    if max_fail_first_n < 0 or max_retry_after_seconds < 0 or max_stall_seconds < 0:
        raise ValueError("timing_profiles bounds must be non-negative")

    # Lazy import: Hypothesis is an optional extra, only needed for fuzzing.
    from hypothesis import strategies as st

    return st.builds(
        TimingProfile,
        fail_first_n=st.integers(min_value=0, max_value=max_fail_first_n),
        retry_after_seconds=st.integers(min_value=0, max_value=max_retry_after_seconds),
        stall_seconds=st.floats(
            min_value=0.0,
            max_value=max_stall_seconds,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


__all__ = [
    "FuzzedTransientFailure",
    "TimingProfile",
    "timing_profiles",
]
