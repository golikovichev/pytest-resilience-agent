"""Integration tests that prove each chaos scenario really injects failures.

These tests directly drive httpx against the controller's mocked target
URLs and check the responses. They are the smoking-gun proof that the
plugin does what the README claims.
"""

from __future__ import annotations

import json

import httpx
import pytest

from pytest_resilience_agent.chaos import ChaosController

# The suite stays fast because no scenario sleeps: timeouts are simulated by
# raising httpx.ReadTimeout directly under the mocked transport, so there is no
# real wait to make assertions flaky on slow CI.


def test_llm_5xx_returns_502_then_succeeds() -> None:
    """llm_5xx: first POST returns 502, second succeeds with payload."""
    controller = ChaosController(scenarios=["llm_5xx"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r1 = client.post(controller.target_gateway_url, json={"q": 1})
            assert r1.status_code == 502
            r2 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r2.status_code == 200
            assert r2.json()["choices"][0]["message"]["content"] == "recovered"
    finally:
        controller.exit()


def test_rate_limit_returns_429_with_retry_after() -> None:
    """rate_limit: first POST returns 429 with Retry-After header."""
    controller = ChaosController(scenarios=["rate_limit"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r1 = client.post(controller.target_gateway_url, json={"q": 1})
            assert r1.status_code == 429
            assert r1.headers.get("Retry-After") == "2"
            r2 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r2.status_code == 200
    finally:
        controller.exit()


def test_partial_outage_one_failure_then_recovery() -> None:
    """partial_outage: 503 once, then 200. Retry logic should resolve it."""
    controller = ChaosController(scenarios=["partial_outage"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r1 = client.post(controller.target_gateway_url, json={"q": 1})
            assert r1.status_code == 503
            r2 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r2.status_code == 200
            assert "back online" in r2.json()["choices"][0]["message"]["content"]
    finally:
        controller.exit()


def test_mcp_error_returns_jsonrpc_error() -> None:
    """mcp_error: Lark MCP call returns JSON-RPC error envelope."""
    controller = ChaosController(scenarios=["mcp_error"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r = client.post(controller.target_lark_url, json={"jsonrpc": "2.0"})
            assert r.status_code == 200
            body = r.json()
            assert "error" in body
            assert body["error"]["code"] == -32603
    finally:
        controller.exit()


def test_events_capture_calls_intercepted() -> None:
    """After exit, scenario revert events carry calls_intercepted metadata."""
    controller = ChaosController(scenarios=["llm_5xx"])
    controller.enter()
    with httpx.Client() as client:
        client.post(controller.target_gateway_url, json={"q": 1})
        client.post(controller.target_gateway_url, json={"q": 2})
    controller.exit()
    removed = [e for e in controller.events if e.detail == "scenario removed"]
    assert removed
    assert removed[0].metadata["calls_intercepted"] == 2


def test_multiple_scenarios_dont_conflict() -> None:
    """rate_limit on gateway + mcp_error on Lark can be applied together."""
    controller = ChaosController(scenarios=["rate_limit", "mcp_error"])
    controller.enter()
    try:
        with httpx.Client() as client:
            gateway = client.post(controller.target_gateway_url, json={"q": 1})
            assert gateway.status_code == 429
            mcp = client.post(controller.target_lark_url, json={"jsonrpc": "2.0"})
            assert mcp.status_code == 200
            assert "error" in mcp.json()
    finally:
        controller.exit()


def test_cost_exceeded_returns_402() -> None:
    controller = ChaosController(scenarios=["cost_exceeded"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r = client.post(controller.target_gateway_url, json={"q": 1})
            assert r.status_code == 402
            assert r.json()["error"]["type"] == "quota_exceeded"
    finally:
        controller.exit()


def test_wrong_model_returned_serves_unexpected_model() -> None:
    controller = ChaosController(scenarios=["wrong_model_returned"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r = client.post(controller.target_gateway_url, json={"q": 1})
            assert r.status_code == 200
            assert r.json()["model"] == "unexpected-fallback-model-v0"
    finally:
        controller.exit()


def test_stream_stall_returns_empty_content() -> None:
    controller = ChaosController(scenarios=["stream_stall"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r = client.post(controller.target_gateway_url, json={"q": 1})
            assert r.status_code == 200
            assert r.json()["choices"][0]["message"]["content"] == ""
            assert r.json()["x_stream_meta"]["truncated"] is True
    finally:
        controller.exit()


def test_network_blip_raises_connect_error_then_recovers() -> None:
    controller = ChaosController(scenarios=["network_blip"])
    controller.enter()
    try:
        with httpx.Client() as client:
            with pytest.raises(httpx.ConnectError):
                client.post(controller.target_gateway_url, json={"q": 1})
            r2 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r2.status_code == 200
            assert "post-blip ok" in r2.json()["choices"][0]["message"]["content"]
    finally:
        controller.exit()


def test_malformed_json_returns_non_json_body() -> None:
    """malformed_json: gateway returns 200 but the body is an HTML error page.

    Mirrors a misconfigured proxy or CDN that swallows the upstream error and
    serves its own 200 HTML. Agent code that calls response.json() blindly
    raises a JSONDecodeError instead of handling the failure.
    """
    controller = ChaosController(scenarios=["malformed_json"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r = client.post(controller.target_gateway_url, json={"q": 1})
            assert r.status_code == 200
            assert "json" not in r.headers.get("content-type", "").lower()
            with pytest.raises(json.JSONDecodeError):
                r.json()
    finally:
        controller.exit()


def test_llm_timeout_triggers_read_timeout() -> None:
    """llm_timeout makes the mocked gateway raise httpx.ReadTimeout on call."""
    import respx

    from pytest_resilience_agent.scenarios import LLMTimeout

    controller = ChaosController(scenarios=["llm_timeout"])
    mock = respx.mock(assert_all_called=False, assert_all_mocked=False)
    mock.start()
    scenario = LLMTimeout(mock, controller.target_gateway_url, delay_seconds=1.5)
    scenario.apply()
    try:
        with httpx.Client() as client:
            with pytest.raises(httpx.ReadTimeout):
                client.post(controller.target_gateway_url, json={"q": 1})
    finally:
        scenario.revert()
        mock.stop()


def test_auth_expiry_returns_401_then_succeeds() -> None:
    """auth_expiry: first POST 401 (token expired), second succeeds after refresh."""
    controller = ChaosController(scenarios=["auth_expiry"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r1 = client.post(controller.target_gateway_url, json={"q": 1})
            assert r1.status_code == 401
            assert r1.json()["error"]["type"] == "invalid_api_key"
            r2 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r2.status_code == 200
            assert "re-authed" in r2.json()["choices"][0]["message"]["content"]
    finally:
        controller.exit()


def test_context_overflow_returns_400_context_length() -> None:
    """context_overflow: gateway returns 400 context_length_exceeded on every call."""
    controller = ChaosController(scenarios=["context_overflow"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r = client.post(controller.target_gateway_url, json={"q": 1})
            assert r.status_code == 400
            assert r.json()["error"]["code"] == "context_length_exceeded"
    finally:
        controller.exit()


def test_mcp_timeout_raises_read_timeout_on_lark() -> None:
    """mcp_timeout: the MCP (Lark) layer raises httpx.ReadTimeout."""
    controller = ChaosController(scenarios=["mcp_timeout"])
    controller.enter()
    try:
        with httpx.Client() as client:
            with pytest.raises(httpx.ReadTimeout):
                client.post(controller.target_lark_url, json={"jsonrpc": "2.0"})
    finally:
        controller.exit()


def test_compose_sequences_failures_then_recovers() -> None:
    """compose=[rate_limit, partial_outage]: call 1 = 429, call 2 = 503, call 3 = 200."""
    controller = ChaosController(compose=["rate_limit", "partial_outage"])
    controller.enter()
    try:
        with httpx.Client() as client:
            r1 = client.post(controller.target_gateway_url, json={"q": 1})
            assert r1.status_code == 429
            r2 = client.post(controller.target_gateway_url, json={"q": 2})
            assert r2.status_code == 503
            r3 = client.post(controller.target_gateway_url, json={"q": 3})
            assert r3.status_code == 200
            assert r3.json()["choices"][0]["message"]["content"] == "recovered"
    finally:
        controller.exit()


def test_compose_rejects_non_composable_scenario() -> None:
    """compose= with a non-gateway scenario (mcp_error) raises a usage error."""
    with pytest.raises(pytest.UsageError):
        ChaosController(compose=["rate_limit", "mcp_error"])


def test_compose_and_scenarios_are_mutually_exclusive() -> None:
    """Passing both compose= and scenarios= is a usage error."""
    with pytest.raises(pytest.UsageError):
        ChaosController(scenarios=["rate_limit"], compose=["partial_outage"])


def test_two_gateway_scenarios_in_scenarios_list_is_rejected() -> None:
    """Two same-layer scenarios in scenarios= would shadow each other -> usage error."""
    with pytest.raises(pytest.UsageError):
        ChaosController(scenarios=["rate_limit", "llm_5xx"])


def test_gateway_plus_mcp_scenarios_still_allowed() -> None:
    """One gateway + one MCP scenario hit different URLs, so they are allowed."""
    controller = ChaosController(scenarios=["rate_limit", "mcp_error"])
    controller.enter()
    controller.exit()  # no usage error raised
