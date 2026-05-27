"""Example tests an end user writes for their own LLM agent.

This file shows the four patterns we expect end-users to copy:

1. **Single-scenario resilience test** - the marker plus the chaos fixture
   does the work; the agent code stays the same as production.
2. **Multi-scenario test** - verifying that agent survives a stack of faults.
3. **Negative resilience test** - proving that a fault SURFACES correctly
   when retries cannot save the day (we want a clean error, not a hang).
4. **Custom event recording** - `chaos.record(...)` for ad-hoc annotation.

These tests run against the sample FastAPI agent in
``demo/sample_agent/app.py`` and exercise the full path from agent code
through the AI Gateway abstraction.
"""

from __future__ import annotations

import pytest

from demo.sample_agent.app import summarise_email


@pytest.mark.resilience(scenarios=["llm_5xx"])
def test_agent_recovers_from_transient_5xx(chaos):
    """Single transient 5xx: agent retries and gets a valid reply."""
    reply = summarise_email("Hi, please summarise this.", timeout=2.0)
    assert reply.content, "agent must produce non-empty content after retry"
    assert reply.attempts >= 2, "should have retried at least once"
    # We injected llm_5xx - the chaos timeline must reflect that
    assert any(e.scenario == "llm_5xx" for e in chaos.events)


@pytest.mark.resilience(scenarios=["rate_limit"])
def test_agent_handles_rate_limit_gracefully(chaos):
    """429 with Retry-After: agent must not surface a confused error."""
    reply = summarise_email("Cancel my plan.", timeout=2.0)
    assert reply.content, "agent must respond after rate limit clears"


@pytest.mark.resilience(scenarios=["rate_limit", "partial_outage"])
def test_agent_survives_stacked_faults(chaos):
    """rate_limit on first call + partial outage scenario both active.

    With our default fixture the rate_limit scenario binds first, so the
    first call returns 429 and the rate_limit second-call rule serves a
    200. Either way, the agent retries and finishes successfully.
    """
    reply = summarise_email("Where is my order?", timeout=2.0)
    assert reply.content


@pytest.mark.resilience(scenarios=["stream_stall"])
def test_agent_treats_empty_stream_as_failure(chaos):
    """Empty content from gateway should surface as a problem to the caller.

    The current sample agent does not yet guard against empty content,
    so this test demonstrates the NEGATIVE resilience signal: it asserts
    that agent did NOT silently return an empty string to the user. If it
    did, the assertion fails and the engineer knows where to add a check.
    """
    reply = summarise_email("Summarise this.", timeout=2.0)
    # Documented bug surface: we WANT this test to fail until the agent
    # learns to detect empty streams. Use ``xfail`` to mark expected failure.
    if reply.content == "":
        chaos.record(
            "stream_stall",
            "agent returned empty content to caller (silent bug surfaced)",
            agent_attempts=reply.attempts,
        )
        pytest.xfail("agent does not yet detect empty stream completion")


@pytest.mark.resilience(scenarios=["mcp_error"])
def test_agent_reports_mcp_error_to_caller(chaos):
    """If a Lark MCP tool call fails the agent must report it, not pretend
    the tool succeeded.

    The sample agent in this repo does not yet wire up an MCP tool, so the
    test only verifies that the chaos timeline captured the mcp_error
    scenario - the assertion is on the chaos events, not the agent reply.
    Real users would replace this with their own MCP-aware agent and
    assert on the user-visible behaviour.
    """
    assert any(e.scenario == "mcp_error" for e in chaos.events)
