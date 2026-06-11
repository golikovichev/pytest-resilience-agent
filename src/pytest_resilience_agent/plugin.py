"""pytest plugin entry point.

Registers the ``resilience`` marker, the ``ai_gateway`` / ``chaos`` fixtures,
the ``--resilience-record`` JSON timeline export, and the
``pytest_runtest_logreport`` hook that surfaces chaos events in test output.

Example usage in a test file::

    import pytest

    @pytest.mark.resilience(scenarios=["llm_timeout", "rate_limit"])
    def test_chat_fallback(ai_gateway, chaos):
        # chaos injects scenarios from the marker
        # ai_gateway proxies to TrueFoundry-configured fallback chain
        reply = ai_gateway.chat([{"role": "user", "content": "hello"}])
        assert reply.content, "agent must respond even under chaos"
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_resilience_agent.chaos import ChaosController
from pytest_resilience_agent.gateway import AIGatewayClient

# Module-level timeline collector. Populated by the chaos fixture finalizer
# and dumped to disk by pytest_sessionfinish when --resilience-record is set.
_TIMELINE: list[dict] = []


def pytest_sessionstart(session: pytest.Session) -> None:
    """Reset the timeline at the start of every session.

    Pytester runs nested in-process pytest sessions during testing, so
    the module-level _TIMELINE accumulates data across runs. Resetting
    on sessionstart keeps each session's timeline self-contained.
    """
    _TIMELINE.clear()


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``resilience`` marker so ``--strict-markers`` is happy.

    Tests opt into a resilience scenario set with::

        @pytest.mark.resilience(scenarios=["llm_timeout", "mcp_error"])
        def test_agent(...): ...
    """
    config.addinivalue_line(
        "markers",
        "resilience(scenarios, turns): inject chaos before running the test. "
        "scenarios=[...] applies one set for the whole test; turns=[[...], [...]] "
        "binds a set per conversation turn, advanced with chaos.next_turn(). "
        "The two are mutually exclusive.",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register CLI options for the resilience plugin.

    --resilience-gateway-url: base URL for the AI Gateway proxy (TrueFoundry)
    --resilience-lark-url: base URL for the Lark MCP server
    --resilience-record: write chaos events to a JSON timeline file
    """
    parser.addoption(
        "--resilience-gateway-url",
        action="store",
        default=None,
        help="Base URL for the AI Gateway (TrueFoundry). Falls back to TFY_GATEWAY_URL env var.",
    )
    parser.addoption(
        "--resilience-lark-url",
        action="store",
        default=None,
        help="Base URL for the Lark MCP server. Falls back to LARK_MCP_URL env var.",
    )
    parser.addoption(
        "--resilience-record",
        action="store",
        default=None,
        help="Path to write a JSON timeline of chaos events injected during the run.",
    )


@pytest.fixture
def ai_gateway(request: pytest.FixtureRequest) -> AIGatewayClient:
    """Return an AIGatewayClient pointed at the configured TrueFoundry gateway.

    The gateway URL comes from ``--resilience-gateway-url`` or the
    ``TFY_GATEWAY_URL`` env var. If neither is set the fixture skips the
    test rather than silently hitting OpenAI directly.
    """
    url = request.config.getoption("--resilience-gateway-url")
    if url is None:
        import os

        url = os.environ.get("TFY_GATEWAY_URL")
    if not url:
        pytest.skip(
            "no AI gateway URL configured (set --resilience-gateway-url or TFY_GATEWAY_URL)"
        )
    return AIGatewayClient(base_url=url)


@pytest.fixture
def chaos(request: pytest.FixtureRequest) -> ChaosController:
    """Return a ChaosController that injects scenarios declared on the marker.

    Reads the ``resilience`` marker from the test item, applies the named
    scenarios for the duration of the test, and cleans up on teardown.
    Target URLs come from the same CLI options/env vars as ``ai_gateway``.
    """
    import os

    marker = request.node.get_closest_marker("resilience")
    scenarios = list(marker.kwargs.get("scenarios", [])) if marker else []
    turns = marker.kwargs.get("turns") if marker else None
    gateway_url = request.config.getoption("--resilience-gateway-url") or os.environ.get(
        "TFY_GATEWAY_URL"
    )
    lark_url = request.config.getoption("--resilience-lark-url") or os.environ.get("LARK_MCP_URL")
    controller = ChaosController(
        scenarios=scenarios,
        turns=turns,
        target_gateway_url=gateway_url,
        target_lark_url=lark_url,
    )
    controller.enter()
    yield controller
    controller.exit()
    # Record this test's chaos timeline for the session-level export.
    _TIMELINE.append(
        {
            "test": request.node.nodeid,
            "scenarios": scenarios,
            "events": [
                {
                    "scenario": e.scenario,
                    "detail": e.detail,
                    "metadata": e.metadata,
                }
                for e in controller.events
            ],
        }
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Surface chaos events alongside the test outcome.

    For each test that used the chaos fixture, append a one-line summary
    so the pytest output reads e.g. ``[chaos] llm_5xx (2 calls), rate_limit (1 call)``.
    """
    if report.when != "call":
        return
    for entry in _TIMELINE:
        if entry["test"] != report.nodeid:
            continue
        summary_parts: list[str] = []
        # Aggregate the "scenario removed" events that carry calls_intercepted
        for event in entry["events"]:
            if event["detail"] == "scenario removed":
                calls = event["metadata"].get("calls_intercepted", 0)
                summary_parts.append(f"{event['scenario']} ({calls} calls)")
        if summary_parts:
            report.sections.append(("chaos events", ", ".join(summary_parts)))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write the chaos timeline to disk if --resilience-record was provided."""
    path = session.config.getoption("--resilience-record")
    if not path or not _TIMELINE:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_TIMELINE, indent=2), encoding="utf-8")
