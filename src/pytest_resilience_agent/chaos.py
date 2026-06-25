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

import pytest
import respx
from opentelemetry import trace

from pytest_resilience_agent.scenarios import (
    CompositeScenario,
    Scenario,
    build_scenario,
    composable_scenarios,
    registered_scenarios,
)

# Scenarios that hit the Lark MCP layer rather than the gateway.
_LARK_LAYER_SCENARIOS = frozenset({"mcp_error", "mcp_timeout"})

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
        scenarios: list[str] | None = None,
        target_gateway_url: str | None = None,
        target_lark_url: str | None = None,
        turns: list[list[str]] | None = None,
        compose: list[str] | None = None,
    ) -> None:
        modes = [bool(scenarios), turns is not None, compose is not None]
        if sum(modes) > 1:
            raise pytest.UsageError(
                "resilience marker accepts only one of scenarios=, turns= or compose="
            )
        if turns is not None:
            if not turns:
                raise pytest.UsageError("turns= must list at least one turn")
            known = set(registered_scenarios())
            unknown = [n for turn in turns for n in turn if n not in known]
            if unknown:
                raise pytest.UsageError(
                    f"unknown chaos scenario(s) in turns=: {sorted(set(unknown))}. "
                    f"Registered: {sorted(known)}"
                )
        if compose is not None:
            if not compose:
                raise pytest.UsageError("compose= must list at least one scenario")
            composable = set(composable_scenarios())
            non_composable = [n for n in compose if n not in composable]
            if non_composable:
                raise pytest.UsageError(
                    f"non-composable scenario(s) in compose=: {sorted(set(non_composable))}. "
                    f"Composable (gateway failures): {sorted(composable)}"
                )
        if scenarios and len(scenarios) > 1:
            # Every gateway-layer scenario installs a route on the same gateway
            # URL, and respx is last-route-wins, so two of them would silently
            # shadow each other (same for the MCP layer). Catch it loudly and
            # point at compose=, which sequences gateway failures on one route.
            gateway_layer = [n for n in scenarios if n not in _LARK_LAYER_SCENARIOS]
            mcp_layer = [n for n in scenarios if n in _LARK_LAYER_SCENARIOS]
            for layer, group in (("gateway", gateway_layer), ("MCP", mcp_layer)):
                if len(group) > 1:
                    raise pytest.UsageError(
                        f"scenarios={sorted(group)} all hit the {layer} endpoint and would "
                        f"silently shadow each other (last route wins). Use compose= to "
                        f"sequence gateway failures, or split them across separate tests."
                    )
        self.scenario_names = list(scenarios) if scenarios else []
        self.turns = turns
        self.compose = list(compose) if compose else None
        self.target_gateway_url = target_gateway_url or self.DEFAULT_GATEWAY_URL
        self.target_lark_url = target_lark_url or self.DEFAULT_LARK_URL
        self.events: list[ChaosEvent] = []
        self._mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
        self._scenarios: list[Scenario] = []
        self._turn_index = 0

    @property
    def current_turn(self) -> int:
        """Zero-based index of the active conversation turn (0 in single-window mode)."""
        return self._turn_index

    def _apply_scenarios(self, names: list[str]) -> None:
        """Build, apply and record one set of scenarios against the live mock."""
        for name in names:
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

    def _apply_turn(self, index: int) -> None:
        """Activate the scenarios for one conversation turn and mark the boundary."""
        assert self.turns is not None
        self._turn_index = index
        names = list(self.turns[index])
        with _TRACER.start_as_current_span(f"chaos.turn.{index}") as span:
            span.set_attribute("chaos.turn.scenarios", names)
            # Apply inside the turn span so the chaos.apply.* spans nest under it.
            self._apply_scenarios(names)

    def _revert_current(self) -> None:
        """Revert (record stats for) every scenario active in the current turn."""
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

    def next_turn(self) -> None:
        """Advance to the next conversation turn: revert this turn's chaos, drop the
        mock's routes and call history, then apply the next turn's scenarios.

        Counters reset because each turn builds brand-new Scenario instances (each
        starts at zero calls). Clearing the mock removes the previous turn's routes
        and the accumulated call records, so a long conversation does not grow them
        unbounded."""
        if self.turns is None:
            raise pytest.UsageError("next_turn() requires turns= on the resilience marker")
        if self._turn_index + 1 >= len(self.turns):
            raise pytest.UsageError(
                f"next_turn() advanced past the last defined turn "
                f"(have {len(self.turns)} turns, already at turn {self._turn_index})"
            )
        self._revert_current()
        self._mock.reset()  # drop accumulated call records
        self._mock.clear()  # drop the previous turn's routes
        self._apply_turn(self._turn_index + 1)

    def _apply_compose(self, steps: list[str]) -> None:
        """Install one composite scenario that walks a sequence of gateway failures."""
        scenario = CompositeScenario(self._mock, self.target_gateway_url, steps)
        result = scenario.apply()
        self._scenarios.append(scenario)
        self.events.append(
            ChaosEvent(
                scenario=result.scenario,
                detail=result.detail,
                metadata=result.metadata,
            )
        )
        with _TRACER.start_as_current_span("chaos.compose") as span:
            span.set_attribute("chaos.compose.steps", steps)

    def enter(self) -> None:
        """Start respx and install scenarios for turn 0 (or the single window)."""
        self._mock.start()
        if self.turns is not None:
            self._apply_turn(0)
        elif self.compose is not None:
            self._apply_compose(self.compose)
        else:
            self._apply_scenarios(self.scenario_names)

    def exit(self) -> None:
        """Revert every scenario in LIFO order and stop respx."""
        self._revert_current()
        self._mock.stop()

    def record(self, scenario: str, detail: str, **metadata: Any) -> None:
        """Append a custom chaos event from inside user code."""
        self.events.append(ChaosEvent(scenario=scenario, detail=detail, metadata=metadata))

    def _target_for(self, scenario_name: str) -> str:
        """Pick gateway URL or Lark URL depending on which layer the scenario hits."""
        if scenario_name in _LARK_LAYER_SCENARIOS:
            return self.target_lark_url
        return self.target_gateway_url


__all__ = [
    "ChaosController",
    "ChaosEvent",
    "composable_scenarios",
    "registered_scenarios",
]
