"""Sample LLM-powered FastAPI agent.

This is the «application under test» that the demo exercises. The agent
calls the AI Gateway to summarise customer emails, with one retry on
non-success status codes and a clear error path when the gateway itself
fails persistently. It is intentionally minimal so the resilience
properties stand out.

Run standalone for sanity check::

    uvicorn demo.sample_agent.app:app --reload
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

GATEWAY_URL = os.environ.get("TFY_GATEWAY_URL", "https://gateway.local/v1/chat/completions")
MAX_RETRIES = 2
RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class AgentReply:
    """Result returned by the agent."""

    content: str
    attempts: int
    fallback_used: bool


class SummariseRequest(BaseModel):
    """POST body for the summarise endpoint."""

    email_body: str


class SummariseResponse(BaseModel):
    """Response payload."""

    summary: str
    attempts: int
    fallback_used: bool


def _post_chat(client: httpx.Client, prompt: str) -> httpx.Response:
    """Single chat completion call. Caller handles retries / errors."""
    return client.post(
        GATEWAY_URL,
        json={
            "model": "gateway-default",
            "messages": [
                {"role": "system", "content": "Summarise customer emails in one sentence."},
                {"role": "user", "content": prompt},
            ],
        },
    )


def summarise_email(prompt: str, timeout: float = 5.0) -> AgentReply:
    """Try the gateway, retry once on transient status, then surface error.

    Returns AgentReply on success. Raises HTTPException on persistent
    failure so FastAPI surfaces a clear 5xx to the caller (the test then
    asserts on the error path).
    """
    attempts = 0
    fallback_used = False
    with httpx.Client(timeout=timeout) as client:
        for _ in range(MAX_RETRIES + 1):
            attempts += 1
            try:
                response = _post_chat(client, prompt)
            except httpx.ReadTimeout as exc:
                # Treat timeout the same as a transient 5xx
                if attempts > MAX_RETRIES:
                    raise HTTPException(504, detail="gateway timeout") from exc
                continue
            if response.status_code in RETRY_STATUS:
                if attempts > MAX_RETRIES:
                    raise HTTPException(
                        503, detail=f"gateway returned {response.status_code} after retries"
                    )
                if response.status_code != 429:
                    fallback_used = True
                continue
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return AgentReply(
                content=content,
                attempts=attempts,
                fallback_used=fallback_used,
            )
    raise HTTPException(500, detail="exhausted retries without a response")


app = FastAPI(title="resilience-demo-agent", version="0.1.0")


@app.post("/summarise", response_model=SummariseResponse)
def summarise(req: SummariseRequest) -> SummariseResponse:
    """Summarise the incoming email body through the gateway."""
    reply = summarise_email(req.email_body)
    return SummariseResponse(
        summary=reply.content,
        attempts=reply.attempts,
        fallback_used=reply.fallback_used,
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "version": "0.1.0"}
