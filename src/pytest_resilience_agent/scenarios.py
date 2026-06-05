"""Real chaos scenarios.

Each scenario is a small object that knows how to install and remove a
``respx`` route that intercepts httpx calls outgoing to the gateway or
the Lark MCP server. The ``ChaosController`` calls ``apply()`` on enter
and ``revert()`` on exit.

Why ``respx``: it lets us patch httpx at the transport layer without
monkey-patching the AIGatewayClient, which means the same scenarios
work for any code that uses httpx (including end-user agents).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import respx


@dataclass
class ScenarioResult:
    """Outcome record for one scenario activation."""

    scenario: str
    detail: str
    metadata: dict[str, Any]


class Scenario:
    """Base class. Subclasses implement ``apply`` and ``revert``."""

    name: str = ""

    def __init__(self, mock: respx.MockRouter, target_url: str) -> None:
        self.mock = mock
        self.target_url = target_url
        self._route: respx.Route | None = None
        self._calls = 0

    def apply(self) -> ScenarioResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def revert(self) -> ScenarioResult:
        # respx routes are torn down when the parent MockRouter stops;
        # we just record stats here.
        self._route = None
        return ScenarioResult(
            scenario=self.name,
            detail="scenario removed",
            metadata={"calls_intercepted": self._calls},
        )


# ---------------------------------------------------------------------------
# Scenario: llm_timeout
# ---------------------------------------------------------------------------


class LLMTimeout(Scenario):
    """Gateway response stalls past the request timeout."""

    name = "llm_timeout"

    def __init__(
        self,
        mock: respx.MockRouter,
        target_url: str,
        delay_seconds: float = 35.0,
    ) -> None:
        super().__init__(mock, target_url)
        self.delay_seconds = delay_seconds

    def apply(self) -> ScenarioResult:
        def slow_response(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            # Simulate a long wait. Tests use short timeouts, so this
            # triggers an httpx.ReadTimeout on the caller side.
            time.sleep(self.delay_seconds)
            return httpx.Response(200, json={"choices": []})

        self._route = self.mock.post(self.target_url).mock(side_effect=slow_response)
        return ScenarioResult(
            scenario=self.name,
            detail=f"will sleep {self.delay_seconds}s before responding",
            metadata={"delay_seconds": self.delay_seconds},
        )


# ---------------------------------------------------------------------------
# Scenario: llm_5xx
# ---------------------------------------------------------------------------


class LLM5xx(Scenario):
    """Gateway returns HTTP 5xx for the first N calls, then succeeds."""

    name = "llm_5xx"

    def __init__(
        self,
        mock: respx.MockRouter,
        target_url: str,
        fail_first_n: int = 1,
        status_code: int = 502,
    ) -> None:
        super().__init__(mock, target_url)
        self.fail_first_n = fail_first_n
        self.status_code = status_code

    def apply(self) -> ScenarioResult:
        success_payload = {
            "model": "fallback-model",
            "choices": [{"message": {"role": "assistant", "content": "recovered"}}],
        }

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            if self._calls <= self.fail_first_n:
                return httpx.Response(self.status_code, text="upstream broke")
            return httpx.Response(200, json=success_payload)

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail=f"first {self.fail_first_n} call(s) return {self.status_code}",
            metadata={
                "fail_first_n": self.fail_first_n,
                "status_code": self.status_code,
            },
        )


# ---------------------------------------------------------------------------
# Scenario: rate_limit
# ---------------------------------------------------------------------------


class RateLimit(Scenario):
    """Gateway returns 429 with Retry-After on the first call."""

    name = "rate_limit"

    def __init__(
        self,
        mock: respx.MockRouter,
        target_url: str,
        retry_after_seconds: int = 2,
    ) -> None:
        super().__init__(mock, target_url)
        self.retry_after_seconds = retry_after_seconds

    def apply(self) -> ScenarioResult:
        success_payload = {
            "model": "primary-model",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            if self._calls == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": str(self.retry_after_seconds)},
                    text="rate limited",
                )
            return httpx.Response(200, json=success_payload)

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail=f"first call 429 Retry-After {self.retry_after_seconds}s",
            metadata={"retry_after_seconds": self.retry_after_seconds},
        )


# ---------------------------------------------------------------------------
# Scenario: mcp_error
# ---------------------------------------------------------------------------


class MCPError(Scenario):
    """Lark MCP server raises a tool error mid-conversation."""

    name = "mcp_error"

    def apply(self) -> ScenarioResult:
        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            # JSON-RPC error envelope per Lark MCP docs
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": "Internal tool error",
                        "data": {"tool": "list_tests"},
                    },
                    "id": 1,
                },
            )

        # Lark MCP transport speaks plain HTTP POST in our wrapper, so we
        # patch any POST to the configured Lark base URL.
        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail="MCP returns JSON-RPC error -32603 on next tool call",
            metadata={"jsonrpc_error_code": -32603},
        )


# ---------------------------------------------------------------------------
# Scenario: partial_outage
# ---------------------------------------------------------------------------


class PartialOutage(Scenario):
    """First call 503, second succeeds. Verifies retry/fallback path."""

    name = "partial_outage"

    def apply(self) -> ScenarioResult:
        success_payload = {
            "model": "primary-model",
            "choices": [{"message": {"role": "assistant", "content": "back online"}}],
        }

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            if self._calls == 1:
                return httpx.Response(503, text="upstream unavailable")
            return httpx.Response(200, json=success_payload)

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail="first call 503, retry succeeds",
            metadata={"first_call_status": 503},
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Scenario: cost_exceeded
# ---------------------------------------------------------------------------


class CostExceeded(Scenario):
    """Gateway returns 402 Payment Required (cost / quota limit hit)."""

    name = "cost_exceeded"

    def apply(self) -> ScenarioResult:
        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            return httpx.Response(
                402,
                json={"error": {"type": "quota_exceeded", "message": "monthly budget hit"}},
            )

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail="gateway returns 402 quota_exceeded on every call",
            metadata={"status_code": 402},
        )


# ---------------------------------------------------------------------------
# Scenario: wrong_model_returned
# ---------------------------------------------------------------------------


class WrongModelReturned(Scenario):
    """Gateway silently routes to unintended fallback model.

    Realistic case: TF gateway downgrades from primary to cheaper backup
    without the caller noticing. Agent code that pins on model name will
    detect it; agent code that does not should fail this resilience test.
    """

    name = "wrong_model_returned"

    def apply(self) -> ScenarioResult:
        payload = {
            "model": "unexpected-fallback-model-v0",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I'm a much smaller model than you asked for.",
                    }
                }
            ],
        }

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            return httpx.Response(200, json=payload)

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail="gateway routes to unexpected-fallback-model-v0",
            metadata={"served_by": "unexpected-fallback-model-v0"},
        )


# ---------------------------------------------------------------------------
# Scenario: stream_stall
# ---------------------------------------------------------------------------


class StreamStall(Scenario):
    """Gateway returns 200 but with truncated / empty content payload.

    Simulates a streaming connection that drops mid-response. Agent code
    that does not validate output length surfaces this as a silent quality
    bug.
    """

    name = "stream_stall"

    def apply(self) -> ScenarioResult:
        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            return httpx.Response(
                200,
                json={
                    "model": "primary-model",
                    "choices": [{"message": {"role": "assistant", "content": ""}}],
                    "x_stream_meta": {"truncated": True, "reason": "upstream_close"},
                },
            )

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail="gateway returns 200 with empty content (stream drop)",
            metadata={"truncated": True},
        )


# ---------------------------------------------------------------------------
# Scenario: network_blip
# ---------------------------------------------------------------------------


class NetworkBlip(Scenario):
    """First N calls raise ConnectError; subsequent calls succeed.

    Mirrors a brief network partition / DNS hiccup at the client side.
    """

    name = "network_blip"

    def __init__(
        self,
        mock: respx.MockRouter,
        target_url: str,
        fail_first_n: int = 1,
    ) -> None:
        super().__init__(mock, target_url)
        self.fail_first_n = fail_first_n

    def apply(self) -> ScenarioResult:
        success_payload = {
            "model": "primary-model",
            "choices": [{"message": {"role": "assistant", "content": "post-blip ok"}}],
        }

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            if self._calls <= self.fail_first_n:
                raise httpx.ConnectError("simulated network blip", request=request)
            return httpx.Response(200, json=success_payload)

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail=f"ConnectError on first {self.fail_first_n} call(s)",
            metadata={"fail_first_n": self.fail_first_n},
        )


# ---------------------------------------------------------------------------
# Scenario: malformed_json
# ---------------------------------------------------------------------------


class MalformedJSON(Scenario):
    """Gateway returns 200 but with a non-JSON body (an HTML error page).

    Mirrors a proxy or CDN that swallows the upstream failure and serves its
    own 200 HTML. Agent code that calls ``response.json()`` without guarding
    against decode errors surfaces this as an unhandled exception rather than
    a graceful fallback.
    """

    name = "malformed_json"

    def apply(self) -> ScenarioResult:
        body = "<html><body><h1>502 Bad Gateway</h1></body></html>"

        def routed(request: httpx.Request) -> httpx.Response:
            self._calls += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=body,
            )

        self._route = self.mock.post(self.target_url).mock(side_effect=routed)
        return ScenarioResult(
            scenario=self.name,
            detail="gateway returns 200 with an HTML body instead of JSON",
            metadata={"content_type": "text/html"},
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, Callable[[respx.MockRouter, str], Scenario]] = {
    LLMTimeout.name: lambda mock, url: LLMTimeout(mock, url),
    LLM5xx.name: lambda mock, url: LLM5xx(mock, url),
    RateLimit.name: lambda mock, url: RateLimit(mock, url),
    MCPError.name: lambda mock, url: MCPError(mock, url),
    PartialOutage.name: lambda mock, url: PartialOutage(mock, url),
    CostExceeded.name: lambda mock, url: CostExceeded(mock, url),
    WrongModelReturned.name: lambda mock, url: WrongModelReturned(mock, url),
    StreamStall.name: lambda mock, url: StreamStall(mock, url),
    NetworkBlip.name: lambda mock, url: NetworkBlip(mock, url),
    MalformedJSON.name: lambda mock, url: MalformedJSON(mock, url),
}


def build_scenario(name: str, mock: respx.MockRouter, target_url: str) -> Scenario:
    """Return a scenario instance for the given registered name.

    Raises ValueError if the name is unknown so typos surface early
    instead of silently doing nothing under the marker.
    """
    if name not in _REGISTRY:
        raise ValueError(f"unknown chaos scenario {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name](mock, target_url)


def registered_scenarios() -> list[str]:
    """Return the list of built-in scenario names."""
    return sorted(_REGISTRY)
