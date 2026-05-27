"""Chaos scenario controller - real implementation.

The controller owns a single ``respx.MockRouter`` and one scenario object
per requested name. On enter, it starts the mock and applies every
scenario. On exit, it reverts each scenario (so cleanup is deterministic)
and stops the mock.

OpenTelemetry: every scenario activation / deactivation / call interception
emits a span on the ``pytest-resilience-agent`` tracer so downstream
observability tooling sees the chaos events alongside real spans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import respx
from opentelemetry import trace

from pytest_resilience_agent.scenarios import (
    Scenario,
    build_scenario,
    registered_scenarios,
)

_TRACER = trace.get_tracer("pytest-resilience-agent")


@dataclass
class ChaosEvent:
    """One chaos event captured for the test report."""

    scenario: str
    detail: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ChaosController:
    """Apply a set of chaos scenarios against a target HTTP host for one test.

    Default target URL is ``https://gateway.local/v1/chat/completions``.
    Override with ``target_gateway_url`` / ``target_lark_url`` when the test
    fixtures know real URLs.
    """

    DEFAULT_GATEWAY_URL = "https://gateway.local/v1/chat/completions"
    DEFAULT_LARK_URL = "https://lark.local"

    def __init__(
        self,
        scenarios: list[str],
        target_gateway_url: str | None = None,
        target_lark_url: str | None = None,
    ) -> None:
        self.scenario_names = scenarios
        self.target_gateway_url = target_gateway_url or self.DEFAULT_GATEWAY_URL
        self.target_lark_url = target_lark_url or self.DEFAULT_LARK_URL
        self.events: list[ChaosEvent] = []
        self._mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
        self._scenarios: list[Scenario] = []

    def enter(self) -> None:
        """Start respx and install every requested scenario."""
        self._mock.start()
        for name in self.scenario_names:
            target = self._target_for(name)
            scenario = build_scenario(name, self._mock, target)
            result = scenario.apply()
            self._scenarios.append(scenario)
            self.events.append(
                ChaosEvent(
                    scenario=result.scenario,
                    detail=result.detail,
                    metadata=result.metadata,
                )
            )
            with _TRACER.start_as_current_span(f"chaos.apply.{name}") as span:
                for k, v in result.metadata.items():
                    span.set_attribute(f"chaos.{k}", v)

    def exit(self) -> None:
        """Revert every scenario in LIFO order and stop respx."""
        for scenario in reversed(self._scenarios):
            result = scenario.revert()
            self.events.append(
                ChaosEvent(
                    scenario=result.scenario,
                    detail=result.detail,
                    metadata=result.metadata,
                )
            )
            with _TRACER.start_as_current_span(f"chaos.revert.{result.scenario}") as span:
                for k, v in result.metadata.items():
                    span.set_attribute(f"chaos.{k}", v)
        self._scenarios.clear()
        self._mock.stop()

    def record(self, scenario: str, detail: str, **metadata: Any) -> None:
        """Append a custom chaos event from inside user code."""
        self.events.append(ChaosEvent(scenario=scenario, detail=detail, metadata=metadata))

    def _target_for(self, scenario_name: str) -> str:
        """Pick gateway URL or Lark URL depending on which layer the scenario hits."""
        if scenario_name == "mcp_error":
            return self.target_lark_url
        return self.target_gateway_url


__all__ = ["ChaosController", "ChaosEvent", "registered_scenarios"]
