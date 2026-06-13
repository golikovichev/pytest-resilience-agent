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

# Faster timeouts so the suite stays quick. Real production timeouts are
# higher; the LLMTimeout test uses 0.2s on the caller and 1.5s on the
# server-side sleep so the assertion is reliable on slow CI.


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
