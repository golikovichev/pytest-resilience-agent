"""Thin client around TrueFoundry AI Gateway.

The gateway is an OpenAI-compatible proxy that handles fallbacks, retries,
and multi-model routing on its side. We just send chat completions through
it and let the gateway config decide what happens when upstream models error.

Docs: https://www.truefoundry.com/docs/ai-gateway/intro-to-llm-gateway
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ChatReply:
    """Minimal reply object returned by ``AIGatewayClient.chat``."""

    content: str
    model: str
    raw: dict[str, Any]


class AIGatewayClient:
    """Send chat completions through a TrueFoundry-style AI Gateway.

    The gateway is OpenAI-compatible, so callers can keep the OpenAI SDK
    interface in their own code and swap the base URL. We keep a thin
    httpx client here to make timeout and error injection easy for tests.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "pytest-resilience-agent/0.1.0 (httpx)",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "gateway-default",
        **kwargs: Any,
    ) -> ChatReply:
        """Send a chat completion request through the gateway.

        The gateway's own config decides fallback chain and retries.
        If the gateway itself is unreachable, raises ``httpx.HTTPError``.
        """
        payload = {"model": model, "messages": messages, **kwargs}
        response = self._client.post(f"{self.base_url}/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""
        return ChatReply(content=content, model=data.get("model", model), raw=data)

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()
