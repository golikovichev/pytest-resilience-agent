"""Mock TrueFoundry AI Gateway for offline demos.

Speaks the same OpenAI-compatible chat completion API as a real
TrueFoundry gateway, with a configurable fallback chain. Each upstream
model is just a small in-process Python function so the whole story runs
without external network access or paid API credits.

Run standalone::

    uvicorn demo.mock_truefoundry:app --port 8800

Or wire it up in the e2e demo by setting::

    TFY_GATEWAY_URL=http://localhost:8800/v1/chat/completions
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "gateway-default"
    messages: list[ChatMessage]


@dataclass
class UpstreamModel:
    """One model in the gateway's fallback chain."""

    name: str
    answer_fn: Callable[[list[ChatMessage]], str]
    fail_probability: float = 0.0


def _gemini_style(messages: list[ChatMessage]) -> str:
    last = messages[-1].content if messages else ""
    return f"[gemini-2.5] summary: {last[:60]}"


def _claude_style(messages: list[ChatMessage]) -> str:
    last = messages[-1].content if messages else ""
    return f"[claude-3.5] summary: {last[:60]}"


def _local_style(messages: list[ChatMessage]) -> str:
    last = messages[-1].content if messages else ""
    return f"[local-llama] summary: {last[:60]}"


# Default fallback chain. The primary fails 30% of the time so callers
# see the fallback exercise. The secondary fails 10%. The local model is
# the safety net.
FALLBACK_CHAIN: list[UpstreamModel] = [
    UpstreamModel("gemini-2.5", _gemini_style, fail_probability=0.3),
    UpstreamModel("claude-3.5", _claude_style, fail_probability=0.1),
    UpstreamModel("local-llama", _local_style, fail_probability=0.0),
]


app = FastAPI(title="mock-truefoundry-gateway", version="0.1.0")


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest) -> dict:
    """Try each upstream in order. Skip on simulated upstream failure."""
    last_error: str | None = None
    for model in FALLBACK_CHAIN:
        if random.random() < model.fail_probability:
            last_error = f"{model.name} simulated upstream failure"
            continue
        content = model.answer_fn(req.messages)
        return {
            "model": model.name,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "x_gateway_meta": {
                "fallback_attempts": FALLBACK_CHAIN.index(model) + 1,
                "selected_model": model.name,
            },
        }
    raise HTTPException(
        status_code=503,
        detail=f"all upstreams failed; last_error={last_error}",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "models": ",".join(m.name for m in FALLBACK_CHAIN)}
