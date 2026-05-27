"""Thin wrapper around the Lark MCP server.

Lark exposes a Model Context Protocol server that lets coding agents
discover, run, and inspect tests. We use it for two things:

1. Listing failing tests in the host repository (input for the agent).
2. Reporting back when a generated resilience test passes (closes loop).

Lark MCP docs: https://docs.getlark.ai/mcp-quickstart
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class LarkTest:
    """One test result returned by Lark."""

    name: str
    status: str
    path: str
    last_failure: str | None = None
    raw: dict[str, Any] | None = None


class LarkMCPClient:
    """Minimal client against a Lark MCP server.

    The MCP server speaks JSON-RPC; this wrapper exposes the two methods
    we need for the resilience-agent MVP. Real MCP transport (stdio /
    websocket) lands in the next iteration. For Day-1 scaffolding the
    client speaks plain HTTP to the Lark control plane.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        app_id: str | None = None,
        app_secret: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._app_id = app_id
        self._app_secret = app_secret
        self._tenant_token: str | None = None
        self._tenant_token_expires_at: float = 0.0
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "pytest-resilience-agent/0.1.0 (httpx)",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def tenant_access_token(self) -> str:
        """Return a cached tenant_access_token, refreshing if near expiry.

        Lark internal apps authenticate every API call with a short-lived
        tenant_access_token (default 7200s). We POST app_id + app_secret to
        ``/auth/v3/tenant_access_token/internal`` and cache the result.

        Raises RuntimeError if app_id / app_secret were not provided.
        """
        if not (self._app_id and self._app_secret):
            raise RuntimeError(
                "tenant_access_token requires app_id and app_secret in client config"
            )
        now = time.time()
        if self._tenant_token and now < self._tenant_token_expires_at - 60:
            return self._tenant_token
        response = self._client.post(
            f"{self.base_url}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"Lark auth failed: code={body.get('code')} msg={body.get('msg')}")
        self._tenant_token = body["tenant_access_token"]
        self._tenant_token_expires_at = now + int(body.get("expire", 7200))
        return self._tenant_token

    def list_failing_tests(self, project: str) -> list[LarkTest]:
        """Return tests currently flagged as failing in the named Lark project.

        Stub MVP version: hits ``/v1/projects/{project}/tests?status=failed``.
        Replace with proper MCP ``tools/call`` once we wire up the JSON-RPC
        transport.
        """
        response = self._client.get(
            f"{self.base_url}/v1/projects/{project}/tests",
            params={"status": "failed"},
        )
        response.raise_for_status()
        payload = response.json()
        out: list[LarkTest] = []
        for row in payload.get("tests", []):
            out.append(
                LarkTest(
                    name=row.get("name", "unknown"),
                    status=row.get("status", "unknown"),
                    path=row.get("path", ""),
                    last_failure=row.get("last_failure"),
                    raw=row,
                )
            )
        return out

    def report_resolved(self, project: str, test_name: str, pytest_path: str) -> None:
        """Tell Lark that a generated pytest case now covers this failure.

        Posts to ``/v1/projects/{project}/tests/{test_name}/resolutions``.
        The Lark UI then shows the pytest path next to the original failure.
        """
        response = self._client.post(
            f"{self.base_url}/v1/projects/{project}/tests/{test_name}/resolutions",
            json={"pytest_path": pytest_path, "source": "pytest-resilience-agent"},
        )
        response.raise_for_status()

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()
