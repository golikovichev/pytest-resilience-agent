"""pytest-resilience-agent: pytest plugin for LLM resilience testing.

Runs your test suite under controlled chaos that proves an LLM application keeps
working when the infrastructure underneath breaks: gateway timeouts, model
brownouts, MCP server errors, rate limits, partial outages, auth expiry,
context overflow, and composed (cascading) failures.
"""

from pytest_resilience_agent.chaos import (
    ChaosController,
    ChaosEvent,
    composable_scenarios,
    registered_scenarios,
)
from pytest_resilience_agent.gateway import AIGatewayClient, ChatReply
from pytest_resilience_agent.scenarios import Scenario, ScenarioResult

__version__ = "1.0.0"

__all__ = [
    "AIGatewayClient",
    "ChaosController",
    "ChaosEvent",
    "ChatReply",
    "Scenario",
    "ScenarioResult",
    "__version__",
    "composable_scenarios",
    "registered_scenarios",
]
